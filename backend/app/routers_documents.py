"""卷宗上传、移动、列表、PDF 预览/下载接口。"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from psycopg.rows import dict_row, tuple_row

from .config import MAX_UPLOAD_MB
from .db import pool
from .models import DocumentOut, MoveDocumentIn
from .pdf_service import save_pdf_then_index, stored_path
from .storage import delete_document_file

router = APIRouter(prefix="/api/cases/{case_id}/documents", tags=["documents"])

_DOC_SELECT = """
    SELECT d.*, f.name AS folder_name
      FROM documents d
      LEFT JOIN folders f ON f.id = d.folder_id
"""


def _resolve_folder(conn, case_id: int, folder_id: int | None) -> bool:
    if folder_id is None:
        return True
    return bool(
        conn.execute(
            "SELECT 1 FROM folders WHERE id=%s AND case_id=%s",
            (folder_id, case_id),
        ).fetchone()
    )


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    case_id: int,
    file: UploadFile = File(...),
    folder_id: int | None = Form(None, description="归入的目录 id，空=未分类"),
) -> DocumentOut:
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

    with pool.connection() as conn:
        conn.row_factory = dict_row
        if not conn.execute("SELECT 1 FROM cases WHERE id=%s", (case_id,)).fetchone():
            raise HTTPException(404, "案件不存在")
        if not _resolve_folder(conn, case_id, folder_id):
            raise HTTPException(400, "所选目录不属于该案件")
        row = conn.execute(
            """
            INSERT INTO documents (case_id, folder_id, filename, stored_name,
                                   size_bytes, status)
            VALUES (%s, %s, %s, '', %s, 'processing')
            RETURNING *
            """,
            (case_id, folder_id, Path(file.filename).name, len(content)),
        ).fetchone()
        row["folder_name"] = None
        conn.commit()
        doc_id = row["id"]

    # PDF 解析/bigram 建索引可能较慢，丢到后台线程，前端轮询状态
    asyncio.get_event_loop().run_in_executor(
        None, save_pdf_then_index, doc_id, Path(file.filename).name, content
    )
    return DocumentOut.model_validate(row)


@router.patch("/{doc_id}/move", response_model=DocumentOut)
def move_document(case_id: int, doc_id: int, payload: MoveDocumentIn) -> DocumentOut:
    """把卷宗移动到另一目录（folder_id=null 表示移到未分类）。"""
    with pool.connection() as conn:
        conn.row_factory = dict_row
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
def document_status(case_id: int, doc_id: int) -> DocumentOut:
    with pool.connection() as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            f"{_DOC_SELECT} WHERE d.id=%s AND d.case_id=%s",
            (doc_id, case_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "卷宗不存在")
    return DocumentOut.model_validate(row)


@router.get("/{doc_id}/preview")
def preview_document(case_id: int, doc_id: int) -> FileResponse:
    """内联返回 PDF，供浏览器 iframe / PDF.js 预览。"""
    return _serve_pdf(case_id, doc_id, inline=True)


@router.get("/{doc_id}/download")
def download_document(case_id: int, doc_id: int) -> FileResponse:
    return _serve_pdf(case_id, doc_id, inline=False)


def _serve_pdf(case_id: int, doc_id: int, inline: bool) -> FileResponse:
    with pool.connection() as conn:
        conn.row_factory = dict_row
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
def remove_document(case_id: int, doc_id: int) -> None:
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
