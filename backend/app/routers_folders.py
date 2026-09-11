"""卷宗目录（文件夹）接口：案件内自定义目录的增删改与排序。"""
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row
from psycopg.errors import UniqueViolation

from .db import pool
from .models import FolderIn, FolderOut

router = APIRouter(prefix="/api/cases/{case_id}/folders", tags=["folders"])


def _case_exists(conn, case_id: int) -> bool:
    return bool(
        conn.execute("SELECT 1 FROM cases WHERE id=%s", (case_id,)).fetchone()
    )


def _get_folder(conn, case_id: int, folder_id: int) -> dict | None:
    return conn.execute(
        """
        SELECT f.*, count(d.id) AS doc_count
          FROM folders f
          LEFT JOIN documents d ON d.folder_id = f.id
         WHERE f.id=%s AND f.case_id=%s
         GROUP BY f.id
        """,
        (folder_id, case_id),
    ).fetchone()


@router.post("", response_model=FolderOut, status_code=201)
def create_folder(case_id: int, payload: FolderIn) -> FolderOut:
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "目录名称不能为空")
    with pool.connection() as conn:
        conn.row_factory = dict_row
        if not _case_exists(conn, case_id):
            raise HTTPException(404, "案件不存在")
        pos = conn.execute(
            """
            SELECT COALESCE(max(position), -1) + 1 AS next_pos
              FROM folders WHERE case_id=%s
            """,
            (case_id,),
        ).fetchone()["next_pos"]
        try:
            row = conn.execute(
                """
                INSERT INTO folders (case_id, name, position)
                VALUES (%s, %s, %s) RETURNING *
                """,
                (case_id, name, pos),
            ).fetchone()
            conn.commit()
        except UniqueViolation:
            conn.rollback()
            raise HTTPException(409, f"目录「{name}」已存在")
        row["doc_count"] = 0
    return FolderOut.model_validate(row)


@router.put("/{folder_id}", response_model=FolderOut)
def rename_folder(
    case_id: int, folder_id: int, payload: FolderIn
) -> FolderOut:
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "目录名称不能为空")
    with pool.connection() as conn:
        conn.row_factory = dict_row
        if not _case_exists(conn, case_id):
            raise HTTPException(404, "案件不存在")
        try:
            updated = conn.execute(
                "UPDATE folders SET name=%s WHERE id=%s AND case_id=%s",
                (name, folder_id, case_id),
            )
            if updated.rowcount == 0:
                raise HTTPException(404, "目录不存在")
            conn.commit()
        except UniqueViolation:
            conn.rollback()
            raise HTTPException(409, f"目录「{name}」已存在")
        row = _get_folder(conn, case_id, folder_id)
    return FolderOut.model_validate(row)


@router.post("/reorder", response_model=list[FolderOut])
def reorder_folders(case_id: int, folder_ids: list[int]) -> list[FolderOut]:
    """按传入的 id 顺序重写 position。"""
    with pool.connection() as conn:
        conn.row_factory = dict_row
        if not _case_exists(conn, case_id):
            raise HTTPException(404, "案件不存在")
        existing = {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM folders WHERE case_id=%s", (case_id,)
            ).fetchall()
        }
        if set(folder_ids) != existing or len(folder_ids) != len(existing):
            raise HTTPException(400, "目录列表与该案件现有目录不一致")
        for pos, fid in enumerate(folder_ids):
            conn.execute(
                "UPDATE folders SET position=%s WHERE id=%s AND case_id=%s",
                (pos, fid, case_id),
            )
        conn.commit()
        rows = conn.execute(
            """
            SELECT f.*, count(d.id) AS doc_count
              FROM folders f
              LEFT JOIN documents d ON d.folder_id = f.id
             WHERE f.case_id=%s
             GROUP BY f.id
             ORDER BY f.position, f.id
            """,
            (case_id,),
        ).fetchall()
    return [FolderOut.model_validate(r) for r in rows]


@router.delete("/{folder_id}", status_code=204)
def remove_folder(case_id: int, folder_id: int) -> None:
    """删除目录；其内卷宗自动回到「未分类」（外键 ON DELETE SET NULL）。"""
    with pool.connection() as conn:
        if not _case_exists(conn, case_id):
            raise HTTPException(404, "案件不存在")
        cur = conn.execute(
            "DELETE FROM folders WHERE id=%s AND case_id=%s",
            (folder_id, case_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "目录不存在")
        conn.commit()
