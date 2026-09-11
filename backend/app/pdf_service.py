"""PDF 存储、逐页文本抽取与全文索引。"""
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


def index_document(document_id: int) -> None:
    """读取已落盘的 PDF，逐页抽取文本、构造 bigram 向量写入 document_pages。"""
    with pool.connection() as conn:
        conn.row_factory = tuple_row
        row = conn.execute(
            "SELECT stored_name FROM documents WHERE id = %s", (document_id,)
        ).fetchone()
        if row is None:
            return
        pdf_path = stored_path(document_id, row[0])

        try:
            doc = fitz.open(pdf_path)
        except Exception as exc:  # 文件损坏 / 非 PDF
            conn.execute(
                "UPDATE documents SET status='failed', error=%s WHERE id=%s",
                (f"无法打开 PDF：{exc}", document_id),
            )
            conn.commit()
            return

        try:
            pages_payload = []
            for page_no, page in enumerate(doc, start=1):
                text = (page.get_text("text") or "").strip()
                if len(text) > MAX_PAGE_CHARS:
                    text = text[:MAX_PAGE_CHARS]
                token_stream = index_tokens(text)
                pages_payload.append((document_id, page_no, text, token_stream))

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
            conn.execute(
                """
                UPDATE documents
                   SET status='indexed', page_count=%s, error=NULL,
                       indexed_at=now()
                 WHERE id=%s
                """,
                (len(doc), document_id),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            conn.execute(
                "UPDATE documents SET status='failed', error=%s WHERE id=%s",
                (f"索引失败：{exc}", document_id),
            )
            conn.commit()
        finally:
            doc.close()


def save_pdf_then_index(document_id: int, filename: str, content: bytes) -> None:
    safe_stem = Path(filename).stem[:80].replace("/", "_")
    stored_name = f"{uuid.uuid4().hex}_{safe_stem}.pdf"
    path = stored_path(document_id, stored_name)
    path.write_bytes(content)
    with pool.connection() as conn:
        conn.row_factory = tuple_row
        conn.execute(
            "UPDATE documents SET filename=%s, stored_name=%s, size_bytes=%s WHERE id=%s",
            (filename, stored_name, len(content), document_id),
        )
        conn.commit()
    index_document(document_id)
