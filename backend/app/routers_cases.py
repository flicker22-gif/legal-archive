"""案件相关接口（含保密级别与角色权限）。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row, tuple_row

from .db import pool
from .models import (
    CaseDetail,
    CaseIn,
    CaseOut,
    DocumentOut,
    FolderOut,
    SECURITY_LEVELS,
    SecurityLevelIn,
)
from .permissions import (
    can_manage,
    can_view,
    current_role,
    require_manage,
    require_set_security,
)
from .storage import delete_case_files

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _row_to_case(row: dict) -> CaseOut:
    return CaseOut.model_validate(row)


@router.post("", response_model=CaseOut, status_code=201)
def create_case(
    payload: CaseIn, role: str = Depends(current_role)
) -> CaseOut:
    require_manage(role)
    level = payload.normalized_level()
    if level != "normal":
        require_set_security(role)  # 仅合伙人可在建案时指定秘密/机密
    with pool.connection() as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            """
            INSERT INTO cases (case_no, title, cause, parties, lawyer, remark,
                               security_level)
            VALUES (%(case_no)s, %(title)s, %(cause)s, %(parties)s,
                    %(lawyer)s, %(remark)s, %(level)s)
            RETURNING *
            """,
            {**payload.model_dump(), "level": level},
        ).fetchone()
        case_id = row["id"]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO folders (case_id, name, position) VALUES (%s, %s, %s)",
                [(case_id, name, pos)
                 for pos, name in enumerate(("诉讼文书", "证据材料", "裁判文书"))],
            )
        conn.commit()
    return _row_to_case(row)


@router.get("", response_model=dict)
def list_cases(
    q: str | None = Query(None, description="按案号/名称/当事人/律师过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: str = Depends(current_role),
) -> dict:
    where, params = "", {"q": None}
    if q and q.strip():
        where = """
            WHERE (case_no ILIKE %(like)s OR title ILIKE %(like)s
               OR parties ILIKE %(like)s OR lawyer ILIKE %(like)s
               OR cause ILIKE %(like)s)
        """
        params["like"] = f"%{q.strip()}%"
    # 律师看不到机密案件；秘书要管理全部案件、合伙人可看全部
    if role == "lawyer":
        where += (" AND " if where else " WHERE ") + \
                 "security_level IN ('normal','secret')"
    with pool.connection() as conn:
        conn.row_factory = dict_row
        total = conn.execute(
            f"SELECT count(*) AS n FROM cases {where}", params
        ).fetchone()["n"]
        rows = conn.execute(
            f"""
            SELECT * FROM cases {where}
            ORDER BY created_at DESC, id DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        ).fetchall()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_row_to_case(r).model_dump() for r in rows],
    }


def _load_case_row(conn, case_id: int) -> dict | None:
    return conn.execute("SELECT * FROM cases WHERE id=%s", (case_id,)).fetchone()


@router.get("/{case_id}", response_model=CaseDetail)
def get_case(
    case_id: int, role: str = Depends(current_role)
) -> CaseDetail:
    with pool.connection() as conn:
        conn.row_factory = dict_row
        case = _load_case_row(conn, case_id)
        if not case:
            raise HTTPException(404, "案件不存在")
        # 无权看内容者：律师对机密案件完全不可见
        if not can_view(role, case["security_level"]) and not can_manage(role):
            raise HTTPException(403, "您的角色无权查看该机密案件")
        folders = conn.execute(
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
        docs = conn.execute(
            """
            SELECT d.*, f.name AS folder_name
              FROM documents d
              LEFT JOIN folders f ON f.id = d.folder_id
             WHERE d.case_id=%s
             ORDER BY d.uploaded_at DESC, d.id DESC
            """,
            (case_id,),
        ).fetchall()
    detail = CaseDetail.model_validate(case)
    detail.folders = [FolderOut.model_validate(f) for f in folders]
    detail.documents = [DocumentOut.model_validate(d) for d in docs]
    return detail


@router.put("/{case_id}", response_model=CaseOut)
def update_case(
    case_id: int, payload: CaseIn, role: str = Depends(current_role)
) -> CaseOut:
    require_manage(role)
    new_level = payload.normalized_level()
    with pool.connection() as conn:
        conn.row_factory = dict_row
        existing = _load_case_row(conn, case_id)
        if not existing:
            raise HTTPException(404, "案件不存在")
        # 保密级别变更仅合伙人
        if new_level != existing["security_level"]:
            require_set_security(role)
        row = conn.execute(
            """
            UPDATE cases SET case_no=%(case_no)s, title=%(title)s,
                   cause=%(cause)s, parties=%(parties)s, lawyer=%(lawyer)s,
                   remark=%(remark)s, security_level=%(level)s
             WHERE id=%(id)s RETURNING *
            """,
            {**payload.model_dump(), "level": new_level, "id": case_id},
        ).fetchone()
        conn.commit()
    if not row:
        raise HTTPException(404, "案件不存在")
    return _row_to_case(row)


@router.patch("/{case_id}/security-level", response_model=CaseOut)
def set_security_level(
    case_id: int, payload: SecurityLevelIn,
    role: str = Depends(current_role),
) -> CaseOut:
    """合伙人调整案件保密级别。"""
    require_set_security(role)
    level = payload.security_level.strip().lower()
    if level not in SECURITY_LEVELS:
        raise HTTPException(400, "保密级别必须是 normal / secret / confidential")
    with pool.connection() as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            "UPDATE cases SET security_level=%s WHERE id=%s RETURNING *",
            (level, case_id),
        ).fetchone()
        conn.commit()
    if not row:
        raise HTTPException(404, "案件不存在")
    return _row_to_case(row)


@router.delete("/{case_id}", status_code=204)
def remove_case(
    case_id: int, role: str = Depends(current_role)
) -> None:
    # 删除整个案件影响重大，仅合伙人
    if role != "partner":
        raise HTTPException(403, "仅合伙人可删除整个案件")
    with pool.connection() as conn:
        conn.row_factory = tuple_row
        rows = conn.execute(
            "SELECT id, stored_name FROM documents WHERE case_id=%s", (case_id,)
        ).fetchall()
        if not conn.execute("SELECT 1 FROM cases WHERE id=%s", (case_id,)).fetchone():
            raise HTTPException(404, "案件不存在")
        conn.execute("DELETE FROM cases WHERE id=%s", (case_id,))
        conn.commit()
    delete_case_files(rows)
