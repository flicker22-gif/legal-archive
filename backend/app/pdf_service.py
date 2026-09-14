"""PDF 存储、逐页文本抽取与全文索引（可恢复的索引任务）。

任务状态机（documents.status）：
    queued → processing → indexed / failed

index_document 是幂等的：只有成功把状态从 queued 认领为 processing 的
执行者才会真正解析；页数据删除/写入与状态翻转在同一个事务里提交，
因此任意时刻一份卷宗最多只有一套页索引。失败原因写入 documents.error，
重试次数见 documents.retry_count（由 indexer / 重试接口维护）。
"""
import uuid
from pathlib import Path

import fitz  # PyMuPDF
from .config import STORAGE_DIR
from .db import pool
from .search import index_tokens

# 连接池会复用连接，必须显式声明本行需要的行工厂，
# 避免被其他调用方设置的 dict_row 污染
from psycopg.rows import tuple_row

# 单页文本入库上限（超长页截断，足够检索与摘要）
MAX_PAGE_CHARS = 20000


def _stored_dir(document_id: int) -> Path:
    # 每 1000 个文档分一个目录，避免单目录文件过多
    d = STORAGE_DIR / f"{document_id // 1000:04d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def stored_path(document_id: int, stored_name: str) -> Path:
    return _stored_dir(document_id) / stored_name


def new_stored_name(filename: str) -> str:
    safe_stem = Path(filename).stem[:80].replace("/", "_")
    return f"{uuid.uuid4().hex}_{safe_stem}.pdf"


def save_uploaded_file(document_id: int, filename: str, content: bytes) -> str:
    """把上传内容写入分桶存储目录，返回 stored_name。"""
    stored_name = new_stored_name(filename)
    stored_path(document_id, stored_name).write_bytes(content)
    return stored_name


def _claim(conn, document_id: int) -> bool:
    """认领任务：仅 queued → processing 成功者继续执行（并发安全）。"""
    cur = conn.execute(
        """
        UPDATE documents
           SET status='processing', task_started_at=now()
         WHERE id=%s AND status='queued'
        """,
        (document_id,),
    )
    conn.commit()
    return cur.rowcount == 1


def _fail(conn, document_id: int, reason: str) -> None:
    """标记失败。带 status 守卫：若任务已被回收重排/完成，不覆盖其状态。"""
    conn.execute(
        """
        UPDATE documents
           SET status='failed', error=%s, task_started_at=NULL
         WHERE id=%s AND status='processing'
        """,
        (reason, document_id),
    )
    conn.commit()


def index_document(document_id: int) -> None:
    """认领并执行索引任务；任何路径都不会让任务停在 processing 伪装成功。"""
    with pool.connection() as conn:
        conn.row_factory = tuple_row
        if not _claim(conn, document_id):
            return  # 已被其他 worker 认领，或状态已变化（删除/重试中）
        row = conn.execute(
            "SELECT stored_name FROM documents WHERE id = %s", (document_id,)
        ).fetchone()
        if row is None:
            return
        stored_name = row[0]
        pdf_path = stored_path(document_id, stored_name) if stored_name else None
        if pdf_path is None or not pdf_path.exists():
            _fail(conn, document_id, "卷宗文件缺失（上传可能未完成），请重新上传")
            return

        try:
            doc = fitz.open(pdf_path)
        except Exception as exc:  # 文件损坏 / 非 PDF
            _fail(conn, document_id, f"无法打开 PDF（文件可能损坏）：{exc}")
            return

        try:
            pages_payload = []
            total_chars = 0
            for page_no, page in enumerate(doc, start=1):
                text = (page.get_text("text") or "").strip()
                if len(text) > MAX_PAGE_CHARS:
                    text = text[:MAX_PAGE_CHARS]
                total_chars += len(text)
                token_stream = index_tokens(text)
                pages_payload.append((document_id, page_no, text, token_stream))
            page_total = len(doc)

            if total_chars == 0:
                _fail(conn, document_id,
                      "未抽取到任何文本：可能是无文本层的扫描件，请先 OCR 再上传")
                return

            # 重试/重索引前先清掉旧页索引；页数据与状态翻转同事务提交，
            # 成功后库里只存在一套页数据
            conn.execute(
                "DELETE FROM document_pages WHERE document_id = %s", (document_id,)
            )
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO document_pages (document_id, page_no, raw_text, tsv)
                    VALUES (%s, %s, %s, to_tsvector('simple', %s))
                    """,
                    pages_payload,
                )
            cur = conn.execute(
                """
                UPDATE documents
                   SET status='indexed', page_count=%s, error=NULL,
                       indexed_at=now(), task_started_at=NULL
                 WHERE id=%s AND status='processing'
                """,
                (page_total, document_id),
            )
            if cur.rowcount == 0:
                # 执行期间被判定超时并重新派工：放弃本次结果，
                # 由新任务落最终状态，避免超时任务伪装成成功
                conn.rollback()
            else:
                conn.commit()
        except Exception as exc:
            conn.rollback()
            _fail(conn, document_id, f"索引失败：{exc}")
        finally:
            doc.close()
