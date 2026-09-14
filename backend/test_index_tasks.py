"""索引任务链路测试：重复上传 / 进程恢复 / 失败重试 / 并发重试 / 权限 / 旧库迁移。

运行（需先启动便携 PG：tools/pgctl.sh start）：
    cd backend && .venv/bin/python -m pytest test_index_tasks.py -v

使用独立测试库 archive_test_tasks 与独立存储目录，不影响开发库数据；
用例全部落库前会重建该测试库，结束后 DROP。
"""
import hashlib
import io
import os
import tempfile
import threading
import time
from pathlib import Path

import psycopg
import pytest

PG_ADMIN_URL = "postgresql://postgres@127.0.0.1:55432/postgres"
TEST_DB = "archive_test_tasks"
TEST_STORAGE = tempfile.mkdtemp(prefix="archive-test-storage-")


def _reset_test_db() -> None:
    with psycopg.connect(PG_ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")


_reset_test_db()

# 必须在 import app 之前注入测试库与测试存储目录
os.environ["DATABASE_URL"] = f"postgresql://postgres@127.0.0.1:55432/{TEST_DB}"
os.environ["STORAGE_DIR"] = TEST_STORAGE

from fastapi.testclient import TestClient  # noqa: E402

from app import indexer  # noqa: E402
from app.config import INDEX_MAX_AUTO_RETRIES  # noqa: E402
from app.db import close_pool, init_pool, init_schema, pool  # noqa: E402
from app.main import app  # noqa: E402
from app.pdf_service import save_uploaded_file, stored_path  # noqa: E402

# ---------------------------------------------------------------- 工具


def make_pdf(text: str, pages: int = 1) -> bytes:
    """生成带文本层的单页/多页 PDF（reportlab CID 中文字体）。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    except Exception:
        pass
    style = ParagraphStyle("t", fontName="STSong-Light", fontSize=12, leading=20)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    story = []
    for i in range(pages):
        story.append(Paragraph(f"{text}（第{i + 1}页）", style))
        if i < pages - 1:
            story.append(PageBreak())
    doc.build(story)
    return buf.getvalue()


GOOD_PDF = make_pdf("房屋租赁合同违约金条款专项测试材料")
GOOD_PDF_B = make_pdf("买卖合同塔式起重机交付验收记录", pages=2)
CORRUPT_PDF = b"%PDF-1.4\nthis is not a real pdf body, truncated garbage"


def client() -> TestClient:
    # 不用 with：连接池由会话级 fixture 管理，避免 lifespan 重复初始化
    return TestClient(app)


def create_case(cl: TestClient, title: str, level: str = "normal") -> int:
    r = cl.post(
        "/api/cases",
        json={"title": title, "parties": "原告：甲\n被告：乙", "lawyer": "测试律师",
              "security_level": level},
        headers={"X-User-Role": "partner"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(cl: TestClient, case_id: int, content: bytes,
           filename: str = "卷宗.pdf", role: str = "secretary"):
    return cl.post(
        f"/api/cases/{case_id}/documents",
        files={"file": (filename, content, "application/pdf")},
        headers={"X-User-Role": role},
    )


def db_rows(sql: str, params=()):
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def db_one(sql: str, params=()):
    rows = db_rows(sql, params)
    return rows[0] if rows else None


def wait_status(doc_id: int, want: tuple[str, ...], timeout: float = 20.0) -> str:
    """轮询直到卷宗进入目标状态集合。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = db_one("SELECT status FROM documents WHERE id=%s", (doc_id,))
        if row and row[0] in want:
            return row[0]
        time.sleep(0.2)
    got = db_one("SELECT status, error FROM documents WHERE id=%s", (doc_id,))
    raise AssertionError(f"doc {doc_id} 未在 {timeout}s 内进入 {want}，当前 {got}")


def stored_pdf_count() -> int:
    return len(list(Path(TEST_STORAGE).rglob("*.pdf")))


# ---------------------------------------------------------------- 夹具


@pytest.fixture(scope="session", autouse=True)
def _lifecycle():
    init_pool()
    init_schema()
    yield
    indexer.shutdown()
    close_pool()
    with psycopg.connect(PG_ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


@pytest.fixture()
def case_id():
    cl = client()
    cid = create_case(cl, f"测试案件 {time.time_ns()}")
    cl.close()
    return cid


# ---------------------------------------------------------------- 重复上传


class TestDuplicateUpload:
    def test_same_content_same_case_returns_existing(self, case_id):
        cl = client()
        before = stored_pdf_count()
        r1 = upload(cl, case_id, GOOD_PDF, "起诉状.pdf")
        assert r1.status_code == 201, r1.text
        doc = r1.json()
        assert doc["deduplicated"] is False
        assert doc["status"] == "queued"
        wait_status(doc["id"], ("indexed",))
        assert stored_pdf_count() == before + 1

        # 同一内容换文件名再传：返回已有卷宗，不重复落盘
        r2 = upload(cl, case_id, GOOD_PDF, "起诉状-副本.pdf")
        assert r2.status_code == 200, r2.text
        dup = r2.json()
        assert dup["deduplicated"] is True
        assert dup["id"] == doc["id"]
        assert dup["filename"] == "起诉状.pdf"  # 返回的是已有卷宗
        assert stored_pdf_count() == before + 1  # 没有新文件落盘

        assert db_one(
            "SELECT count(*) FROM documents WHERE case_id=%s", (case_id,)
        )[0] == 1

        # 检索结果只有一套页，不会因重复上传翻倍
        hits = cl.get("/api/search", params={"q": "违约金", "case_id": case_id},
                      headers={"X-User-Role": "partner"}).json()
        assert hits["total"] == 1
        cl.close()

    def test_same_content_other_case_allowed(self, case_id):
        cl = client()
        other = create_case(cl, "另一个案件")
        r1 = upload(cl, case_id, GOOD_PDF_B, "合同.pdf")
        r2 = upload(cl, other, GOOD_PDF_B, "合同.pdf")
        assert r1.status_code == 201 and r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]
        cl.close()

    def test_different_content_same_case_allowed(self, case_id):
        cl = client()
        r1 = upload(cl, case_id, GOOD_PDF, "材料一.pdf")
        r2 = upload(cl, case_id, GOOD_PDF_B, "材料二.pdf")
        assert r1.status_code == 201 and r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]
        wait_status(r1.json()["id"], ("indexed",))
        wait_status(r2.json()["id"], ("indexed",))
        cl.close()

    def test_concurrent_same_content_upload_only_one_row(self, case_id):
        before = stored_pdf_count()
        results = []

        def do_upload():
            cl = client()
            results.append(upload(cl, case_id, GOOD_PDF, "并发.pdf").status_code)
            cl.close()

        threads = [threading.Thread(target=do_upload) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(results) == [200, 200, 200, 201], results
        assert db_one(
            "SELECT count(*) FROM documents WHERE case_id=%s", (case_id,)
        )[0] == 1
        assert stored_pdf_count() == before + 1  # 只落了一份文件
        doc_id = db_one("SELECT id FROM documents WHERE case_id=%s", (case_id,))[0]
        wait_status(doc_id, ("indexed",))


# ---------------------------------------------------------------- 进程恢复


class TestRecovery:
    def _insert_doc(self, case_id: int, status: str, content: bytes | None,
                    filename: str, retry_count: int = 0) -> int:
        """直接落库模拟各种中断现场（绕过上传接口）。"""
        content_hash = hashlib.sha256(content).hexdigest() if content else None
        with pool.connection() as conn:
            doc_id = conn.execute(
                """
                INSERT INTO documents (case_id, filename, stored_name, size_bytes,
                                       status, content_hash, retry_count)
                VALUES (%s, %s, '', %s, %s, %s, %s)
                RETURNING id
                """,
                (case_id, filename, len(content or b""), status,
                 content_hash, retry_count),
            ).fetchone()[0]
            if content is not None:
                stored_name = save_uploaded_file(doc_id, filename, content)
                conn.execute(
                    "UPDATE documents SET stored_name=%s WHERE id=%s",
                    (stored_name, doc_id),
                )
            conn.commit()
        return doc_id

    def test_startup_recovers_interrupted_tasks(self, case_id):
        # 模拟进程崩溃现场：一个 processing（解析到一半）、一个 queued（未开始）
        crashed = self._insert_doc(case_id, "processing", GOOD_PDF, "崩溃时处理中.pdf")
        pending = self._insert_doc(case_id, "queued", GOOD_PDF_B, "崩溃时排队.pdf")

        ids = indexer.recover_interrupted_tasks()
        assert crashed in ids and pending in ids

        assert wait_status(crashed, ("indexed",)) == "indexed"
        assert wait_status(pending, ("indexed",)) == "indexed"
        # 中断的 processing 记了一次重试；queued 未开始不计
        assert db_one("SELECT retry_count FROM documents WHERE id=%s",
                      (crashed,))[0] == 1
        assert db_one("SELECT retry_count FROM documents WHERE id=%s",
                      (pending,))[0] == 0
        # 恢复后可正常检索
        cl = client()
        hits = cl.get("/api/search", params={"q": "违约金", "case_id": case_id},
                      headers={"X-User-Role": "partner"}).json()
        assert hits["total"] == 1
        cl.close()

    def test_exhausted_task_fails_instead_of_fake_success(self, case_id):
        # 自动重试已耗尽的 processing 任务：恢复时必须明确失败，不能伪装成功
        doc_id = self._insert_doc(
            case_id, "processing", GOOD_PDF, "反复中断.pdf",
            retry_count=INDEX_MAX_AUTO_RETRIES,
        )
        indexer.recover_interrupted_tasks()
        status, error = db_one(
            "SELECT status, error FROM documents WHERE id=%s", (doc_id,))
        assert status == "failed"
        assert "重试" in error
        # 失败任务不得出现在检索结果里
        cl = client()
        hits = cl.get("/api/search", params={"q": "违约金", "case_id": case_id},
                      headers={"X-User-Role": "partner"}).json()
        assert hits["total"] == 0
        cl.close()

    def test_missing_file_fails_with_readable_reason(self, case_id):
        # queued 但磁盘上没有文件（上传被中断）：恢复后明确失败而不是卡住
        doc_id = self._insert_doc(case_id, "queued", None, "半截上传.pdf")
        indexer.recover_interrupted_tasks()
        assert wait_status(doc_id, ("failed",)) == "failed"
        error = db_one("SELECT error FROM documents WHERE id=%s", (doc_id,))[0]
        assert "缺失" in error or "重新上传" in error


# ---------------------------------------------------------------- 失败重试


class TestRetry:
    def _failed_doc(self, cl, case_id: int) -> int:
        r = upload(cl, case_id, CORRUPT_PDF, "损坏卷宗.pdf")
        assert r.status_code == 201, r.text
        doc_id = r.json()["id"]
        assert wait_status(doc_id, ("failed",)) == "failed"
        return doc_id

    def test_failure_keeps_reason_then_retry_succeeds(self, case_id):
        cl = client()
        doc_id = self._failed_doc(cl, case_id)
        row = db_one(
            "SELECT error, retry_count FROM documents WHERE id=%s", (doc_id,))
        assert row[0], "失败必须保留可读原因"
        assert row[1] == 0

        # 修复磁盘上的文件（模拟找回完好原件）后手动重试
        stored_name = db_one(
            "SELECT stored_name FROM documents WHERE id=%s", (doc_id,))[0]
        stored_path(doc_id, stored_name).write_bytes(GOOD_PDF_B)

        r = cl.post(f"/api/cases/{case_id}/documents/{doc_id}/retry",
                    headers={"X-User-Role": "secretary"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "queued"
        assert r.json()["retry_count"] == 1

        assert wait_status(doc_id, ("indexed",)) == "indexed"
        row = db_one(
            """SELECT error, page_count, retry_count, indexed_at IS NOT NULL
                 FROM documents WHERE id=%s""", (doc_id,))
        assert row[0] is None and row[1] == 2 and row[2] == 1 and row[3]

        # 成功后只能有一套页数据（页码不重复、页数一致）
        pages = db_rows(
            "SELECT page_no, count(*) FROM document_pages"
            " WHERE document_id=%s GROUP BY page_no ORDER BY page_no", (doc_id,))
        assert [p[0] for p in pages] == [1, 2]
        assert all(p[1] == 1 for p in pages)

        # 已可检索
        hits = cl.get("/api/search", params={"q": "塔式起重机", "case_id": case_id},
                      headers={"X-User-Role": "partner"}).json()
        assert hits["total"] == 2
        cl.close()

    def test_retry_on_non_failed_conflicts(self, case_id):
        cl = client()
        doc_id = self._failed_doc(cl, case_id)
        stored_name = db_one(
            "SELECT stored_name FROM documents WHERE id=%s", (doc_id,))[0]
        stored_path(doc_id, stored_name).write_bytes(GOOD_PDF)
        assert cl.post(f"/api/cases/{case_id}/documents/{doc_id}/retry",
                       headers={"X-User-Role": "secretary"}).status_code == 200
        wait_status(doc_id, ("indexed",))
        # 已成功后再重试 → 409
        r = cl.post(f"/api/cases/{case_id}/documents/{doc_id}/retry",
                    headers={"X-User-Role": "secretary"})
        assert r.status_code == 409
        assert "失败" in r.json()["detail"]
        cl.close()

    def test_concurrent_retry_only_one_wins(self, case_id):
        cl = client()
        doc_id = self._failed_doc(cl, case_id)
        stored_name = db_one(
            "SELECT stored_name FROM documents WHERE id=%s", (doc_id,))[0]
        stored_path(doc_id, stored_name).write_bytes(GOOD_PDF_B)
        cl.close()

        codes = []

        def do_retry():
            c = client()
            codes.append(
                c.post(f"/api/cases/{case_id}/documents/{doc_id}/retry",
                       headers={"X-User-Role": "partner"}).status_code)
            c.close()

        threads = [threading.Thread(target=do_retry) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert codes.count(200) == 1 and codes.count(409) == 4, codes

        assert wait_status(doc_id, ("indexed",)) == "indexed"
        # 并发重试后仍然只有一套页数据
        pages = db_rows(
            "SELECT page_no, count(*) FROM document_pages"
            " WHERE document_id=%s GROUP BY page_no", (doc_id,))
        assert len(pages) == 2 and all(p[1] == 1 for p in pages)
        assert db_one("SELECT retry_count FROM documents WHERE id=%s",
                      (doc_id,))[0] == 1


# ---------------------------------------------------------------- 权限


class TestPermissions:
    def test_retry_roles(self, case_id):
        cl = client()
        r = upload(cl, case_id, CORRUPT_PDF, "待重试.pdf")
        doc_id = r.json()["id"]
        wait_status(doc_id, ("failed",))

        # 律师无管理权限
        assert cl.post(f"/api/cases/{case_id}/documents/{doc_id}/retry",
                       headers={"X-User-Role": "lawyer"}).status_code == 403
        # 秘书可重试
        assert cl.post(f"/api/cases/{case_id}/documents/{doc_id}/retry",
                       headers={"X-User-Role": "secretary"}).status_code == 200
        wait_status(doc_id, ("failed",))  # 文件仍损坏 → 再次失败
        # 合伙人可重试
        assert cl.post(f"/api/cases/{case_id}/documents/{doc_id}/retry",
                       headers={"X-User-Role": "partner"}).status_code == 200
        wait_status(doc_id, ("failed",))
        cl.close()

    def test_status_visibility_follows_security_rules(self):
        cl = client()
        secret_case = create_case(cl, "秘密案件状态可见性", level="secret")
        conf_case = create_case(cl, "机密案件状态可见性", level="confidential")
        r1 = upload(cl, secret_case, GOOD_PDF, "秘密卷宗.pdf")
        r2 = upload(cl, conf_case, GOOD_PDF, "机密卷宗.pdf")
        d1, d2 = r1.json()["id"], r2.json()["id"]

        # 律师：秘密案件可见状态，机密案件 403
        assert cl.get(f"/api/cases/{secret_case}/documents/{d1}/status",
                      headers={"X-User-Role": "lawyer"}).status_code == 200
        assert cl.get(f"/api/cases/{conf_case}/documents/{d2}/status",
                      headers={"X-User-Role": "lawyer"}).status_code == 403
        # 秘书（管理需要）与合伙人：均可见
        for role in ("secretary", "partner"):
            assert cl.get(f"/api/cases/{conf_case}/documents/{d2}/status",
                          headers={"X-User-Role": role}).status_code == 200
        wait_status(d1, ("indexed",))
        wait_status(d2, ("indexed",))
        cl.close()


# ---------------------------------------------------------------- 旧库迁移


class TestOldSchemaMigration:
    def test_migrate_and_recover_old_database(self):
        """旧库（无指纹/重试/任务时间列）升级：迁移幂等，遗留任务被恢复。"""
        with pool.connection() as conn:
            conn.execute(
                "DROP TABLE IF EXISTS document_pages, documents, folders, cases CASCADE"
            )
            # 旧版本表结构（本次改动之前）
            conn.execute("""
                CREATE TABLE cases (
                    id BIGSERIAL PRIMARY KEY,
                    case_no VARCHAR(100), title VARCHAR(300) NOT NULL,
                    cause VARCHAR(200), parties TEXT NOT NULL,
                    lawyer VARCHAR(100) NOT NULL, remark TEXT,
                    security_level VARCHAR(20) NOT NULL DEFAULT 'normal',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )""")
            conn.execute("""
                CREATE TABLE folders (
                    id BIGSERIAL PRIMARY KEY,
                    case_id BIGINT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                    name VARCHAR(100) NOT NULL, position INT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE (case_id, name)
                )""")
            conn.execute("""
                CREATE TABLE documents (
                    id BIGSERIAL PRIMARY KEY,
                    case_id BIGINT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                    folder_id BIGINT,
                    filename VARCHAR(500) NOT NULL,
                    stored_name VARCHAR(500) NOT NULL,
                    page_count INT NOT NULL DEFAULT 0,
                    size_bytes BIGINT NOT NULL DEFAULT 0,
                    status VARCHAR(20) NOT NULL DEFAULT 'processing',
                    error TEXT,
                    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    indexed_at TIMESTAMPTZ
                )""")
            conn.execute("""
                CREATE TABLE document_pages (
                    id BIGSERIAL PRIMARY KEY,
                    document_id BIGINT NOT NULL REFERENCES documents(id)
                        ON DELETE CASCADE,
                    page_no INT NOT NULL, raw_text TEXT NOT NULL,
                    tsv TSVECTOR NOT NULL, UNIQUE (document_id, page_no)
                )""")
            conn.execute(
                "INSERT INTO cases (title, parties, lawyer) VALUES ('旧库案件','甲','丙')"
            )
            conn.commit()

        # 旧库里一份「处理中」的遗留卷宗（进程曾崩溃）+ 一份已索引卷宗
        with pool.connection() as conn:
            old_case = conn.execute("SELECT id FROM cases ORDER BY id LIMIT 1"
                                    ).fetchone()[0]
            stuck = conn.execute(
                """INSERT INTO documents (case_id, filename, stored_name, size_bytes,
                                          status)
                   VALUES (%s, '旧库遗留.pdf', '', 0, 'processing') RETURNING id""",
                (old_case,),
            ).fetchone()[0]
            stored_name = save_uploaded_file(stuck, "旧库遗留.pdf", GOOD_PDF)
            conn.execute(
                "UPDATE documents SET stored_name=%s WHERE id=%s",
                (stored_name, stuck))
            done = conn.execute(
                """INSERT INTO documents (case_id, filename, stored_name, size_bytes,
                                          status, page_count)
                   VALUES (%s, '旧库已索引.pdf', '', 0, 'indexed', 1) RETURNING id""",
                (old_case,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO document_pages (document_id, page_no, raw_text, tsv)
                   VALUES (%s, 1, '旧索引页', to_tsvector('simple', '旧索 索引'))""",
                (done,))
            conn.commit()

        # 升级迁移（幂等）+ 启动恢复
        init_schema()
        cols = {r[0] for r in db_rows(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name='documents'")}
        assert {"content_hash", "retry_count", "task_started_at"} <= cols
        idx = db_one(
            "SELECT indexname FROM pg_indexes"
            " WHERE tablename='documents' AND indexname='idx_documents_case_hash'")
        assert idx is not None

        indexer.recover_interrupted_tasks()
        assert wait_status(stuck, ("indexed",)) == "indexed"
        # 已索引的旧数据不被触碰
        assert db_one("SELECT status, page_count FROM documents WHERE id=%s",
                      (done,)) == ("indexed", 1)
        assert db_one("SELECT count(*) FROM document_pages WHERE document_id=%s",
                      (done,))[0] == 1
