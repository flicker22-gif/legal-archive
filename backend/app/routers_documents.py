"""卷宗上传、移动、列表、PDF 预览/下载接口（含权限控制）。"""
import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row, tuple_row

from . import indexer
from .config import MAX_UPLOAD_MB
from .db import pool
from .models import DocumentOut, MoveDocumentIn, UploadResult
from .pdf_service import save_uploaded_file, stored_path
from .permissions import (
    can_view,
    current_role,
    require_download,
    require_manage,
    require_view,
)
from .storage import delete_document_file

router = APIRouter(prefix="/api/cases/{case_id}/documents", tags=["documents"])

_DOC_SELECT = """
    SELECT d.*, f.name AS folder_name
      FROM documents d
      LEFT JOIN folders f ON f.id = d.folder_id
"""

# 状态中文名（用于冲突提示）
_STATUS_LABELS = {
    "queued": "排队中",
    "processing": "处理中",
    "indexed": "可检索",
    "failed": "失败",
}


def _case_level(conn, case_id: int) -> str | None:
    """案件保密级别；调用方连接须为 dict_row（本模块统一）。"""
    row = conn.execute(
        "SELECT security_level FROM cases WHERE id=%s", (case_id,)
    ).fetchone()
    return row["security_level"] if row else None


def _resolve_folder(conn, case_id: int, folder_id: int | None) -> bool:
    if folder_id is None:
        return True
    return bool(
        conn.execute(
            "SELECT 1 FROM folders WHERE id=%s AND case_id=%s",
            (folder_id, case_id),
        ).fetchone()
    )


@router.post("", response_model=UploadResult, status_code=201)
async def upload_document(
    case_id: int,
    response: Response,
    role: str = Depends(current_role),
    file: UploadFile = File(...),
    folder_id: int | None = Form(None, description="归入的目录 id，空=未分类"),
) -> UploadResult:
    require_manage(role)
    if (file.content_type or "") not in ("application/pdf", "application/octet-stream") \
            and not file.filename.lower().endswith(".pdf"):
        raise HTTPException(415, "仅支持 PDF 卷宗")

    content = await file.read()
    if not content:
        raise HTTPException(400, "文件为空")
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"文件超过 {MAX_UPLOAD_MB}MB 上限")
    if not content.startswith(b"%PDF"):
        raise HTTPException(400, "文件不是有效的 PDF（缺少 %PDF 文件头）")

    filename = Path(file.filename).name
    # 内容指纹：同一案件下重复上传同一内容时返回已有卷宗，不重复落盘
    content_hash = hashlib.sha256(content).hexdigest()

    with pool.connection() as conn:
        conn.row_factory = dict_row
        level = _case_level(conn, case_id)
        if level is None:
            raise HTTPException(404, "案件不存在")
        if not _resolve_folder(conn, case_id, folder_id):
            raise HTTPException(400, "所选目录不属于该案件")
        try:
            row = conn.execute(
                """
                INSERT INTO documents (case_id, folder_id, filename, stored_name,
                                       size_bytes, status, content_hash)
                VALUES (%s, %s, %s, '', %s, 'queued', %s)
                RETURNING *
                """,
                (case_id, folder_id, filename, len(content), content_hash),
            ).fetchone()
        except UniqueViolation:
            # 并发或重复上传：唯一索引兜底，返回已有卷宗
            conn.rollback()
            existing = conn.execute(
                f"{_DOC_SELECT} WHERE d.case_id=%s AND d.content_hash=%s",
                (case_id, content_hash),
            ).fetchone()
            response.status_code = 200
            return UploadResult.model_validate({**existing, "deduplicated": True})

        doc_id = row["id"]
        try:
            stored_name = save_uploaded_file(doc_id, filename, content)
        except OSError as exc:
            # 文件未落盘则不入库（连接退出时回滚本次 INSERT）
            raise HTTPException(500, f"卷宗文件保存失败，请重新上传：{exc}")
        conn.execute(
            "UPDATE documents SET stored_name=%s WHERE id=%s",
            (stored_name, doc_id),
        )
        conn.commit()
        row = conn.execute(
            f"{_DOC_SELECT} WHERE d.id=%s", (doc_id,)
        ).fetchone()

    # 文件已落盘、任务已排队（queued），后台 worker 认领后解析建索引；
    # 即使此刻进程崩溃，重启恢复也会重新发现该 queued 任务
    indexer.enqueue(doc_id)
    return UploadResult.model_validate({**row, "deduplicated": False})


@router.patch("/{doc_id}/move", response_model=DocumentOut)
def move_document(
    case_id: int, doc_id: int, payload: MoveDocumentIn,
    role: str = Depends(current_role),
) -> DocumentOut:
    """把卷宗移动到另一目录（folder_id=null 表示移到未分类）。"""
    require_manage(role)
    with pool.connection() as conn:
        conn.row_factory = dict_row
        if _case_level(conn, case_id) is None:
            raise HTTPException(404, "案件不存在")
        if not _resolve_folder(conn, case_id, payload.folder_id):
            raise HTTPException(400, "目标目录不属于该案件")
        row = conn.execute(
            f"""
            {_DOC_SELECT}
             WHERE d.id=%s AND d.case_id=%s
            """,
            (doc_id, case_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "卷宗不存在")
        conn.execute(
            "UPDATE documents SET folder_id=%s WHERE id=%s AND case_id=%s",
            (payload.folder_id, doc_id, case_id),
        )
        conn.commit()
        row["folder_id"] = payload.folder_id
        if payload.folder_id is None:
            row["folder_name"] = None
        else:
            row["folder_name"] = conn.execute(
                "SELECT name FROM folders WHERE id=%s", (payload.folder_id,)
            ).fetchone()["name"]
    return DocumentOut.model_validate(row)


@router.get("/{doc_id}/status", response_model=DocumentOut)
def document_status(
    case_id: int, doc_id: int, role: str = Depends(current_role)
) -> DocumentOut:
    with pool.connection() as conn:
        conn.row_factory = dict_row
        level = _case_level(conn, case_id)
        if level is None:
            raise HTTPException(404, "案件不存在")
        # 律师无权访问机密案件；秘书要跟踪上传状态、合伙人全权
        if role == "lawyer" and not can_view(role, level):
            raise HTTPException(403, "您的角色无权访问该机密案件")
        row = conn.execute(
            f"{_DOC_SELECT} WHERE d.id=%s AND d.case_id=%s",
            (doc_id, case_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "卷宗不存在")
    return DocumentOut.model_validate(row)


@router.post("/{doc_id}/retry", response_model=DocumentOut)
def retry_document(
    case_id: int, doc_id: int, role: str = Depends(current_role)
) -> DocumentOut:
    """索引失败的手动重试（秘书/合伙人）：重新排队，成功后旧页索引被整体替换。

    状态翻转带守卫（仅 failed → queued），并发重试只有一个成功，其余 409。
    """
    require_manage(role)
    with pool.connection() as conn:
        conn.row_factory = dict_row
        if _case_level(conn, case_id) is None:
            raise HTTPException(404, "案件不存在")
        cur = conn.execute(
            """
            UPDATE documents
               SET status='queued', task_started_at=NULL,
                   retry_count=retry_count+1
             WHERE id=%s AND case_id=%s AND status='failed'
         RETURNING id
            """,
            (doc_id, case_id),
        )
        if cur.fetchone() is None:
            current = conn.execute(
                "SELECT status FROM documents WHERE id=%s AND case_id=%s",
                (doc_id, case_id),
            ).fetchone()
            if current is None:
                raise HTTPException(404, "卷宗不存在")
            label = _STATUS_LABELS.get(current["status"], current["status"])
            raise HTTPException(
                409, f"卷宗当前状态为「{label}」，仅「失败」状态可重试"
            )
        conn.commit()
        row = conn.execute(
            f"{_DOC_SELECT} WHERE d.id=%s", (doc_id,)
        ).fetchone()
    indexer.enqueue(doc_id)
    return DocumentOut.model_validate(row)


@router.get("/{doc_id}/preview")
def preview_document(
    case_id: int, doc_id: int, role: str = Depends(current_role)
) -> FileResponse:
    """内联返回 PDF 正文，供浏览器 iframe 预览（需查看权限）。"""
    return _serve_pdf(case_id, doc_id, role, inline=True)


@router.get("/{doc_id}/download")
def download_document(
    case_id: int, doc_id: int, role: str = Depends(current_role)
) -> FileResponse:
    return _serve_pdf(case_id, doc_id, role, inline=False)


def _serve_pdf(
    case_id: int, doc_id: int, role: str, inline: bool
) -> FileResponse:
    with pool.connection() as conn:
        conn.row_factory = dict_row
        case = conn.execute(
            "SELECT security_level FROM cases WHERE id=%s", (case_id,)
        ).fetchone()
        if not case:
            raise HTTPException(404, "案件不存在")
        level = case["security_level"]
        if inline:
            require_view(role, level)
        else:
            require_download(role, level)
        row = conn.execute(
            "SELECT * FROM documents WHERE id=%s AND case_id=%s", (doc_id, case_id)
        ).fetchone()
    if not row:
        raise HTTPException(404, "卷宗不存在")
    path = stored_path(doc_id, row["stored_name"])
    if not path.exists():
        raise HTTPException(410, "卷宗文件在磁盘上已丢失")
    disposition = "inline" if inline else "attachment"
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=row["filename"],
        content_disposition_type=disposition,
    )


@router.delete("/{doc_id}", status_code=204)
def remove_document(
    case_id: int, doc_id: int, role: str = Depends(current_role)
) -> None:
    require_manage(role)
    with pool.connection() as conn:
        # 显式 tuple_row：连接会被池复用，行工厂可能被上一个借用者改成 dict
        conn.row_factory = tuple_row
        row = conn.execute(
            "SELECT stored_name FROM documents WHERE id=%s AND case_id=%s",
            (doc_id, case_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "卷宗不存在")
        conn.execute("DELETE FROM documents WHERE id=%s", (doc_id,))
        conn.commit()
    delete_document_file(doc_id, row[0])
