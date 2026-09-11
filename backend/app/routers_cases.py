"""案件相关接口。"""
from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row, tuple_row

from .db import pool
from .models import CaseDetail, CaseIn, CaseOut, DocumentOut
from .storage import delete_case_files

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _row_to_case(row: dict) -> CaseOut:
    return CaseOut.model_validate(row)


@router.post("", response_model=CaseOut, status_code=201)
def create_case(payload: CaseIn) -> CaseOut:
    with pool.connection() as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            """
            INSERT INTO cases (case_no, title, cause, parties, lawyer, remark)
            VALUES (%(case_no)s, %(title)s, %(cause)s, %(parties)s,
                    %(lawyer)s, %(remark)s)
            RETURNING *
            """,
            payload.model_dump(),
        ).fetchone()
        conn.commit()
    return _row_to_case(row)


@router.get("", response_model=dict)
def list_cases(
    q: str | None = Query(None, description="按案号/名称/当事人/律师过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    where, params = "", {"q": None}
    if q and q.strip():
        where = """
            WHERE case_no ILIKE %(like)s OR title ILIKE %(like)s
               OR parties ILIKE %(like)s OR lawyer ILIKE %(like)s
               OR cause ILIKE %(like)s
        """
        params["like"] = f"%{q.strip()}%"
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


@router.get("/{case_id}", response_model=CaseDetail)
def get_case(case_id: int) -> CaseDetail:
    with pool.connection() as conn:
        conn.row_factory = dict_row
        case = conn.execute("SELECT * FROM cases WHERE id=%s", (case_id,)).fetchone()
        if not case:
            raise HTTPException(404, "案件不存在")
        docs = conn.execute(
            """
            SELECT * FROM documents WHERE case_id=%s
            ORDER BY uploaded_at DESC, id DESC
            """,
            (case_id,),
        ).fetchall()
    detail = CaseDetail.model_validate(case)
    detail.documents = [DocumentOut.model_validate(d) for d in docs]
    return detail


@router.put("/{case_id}", response_model=CaseOut)
def update_case(case_id: int, payload: CaseIn) -> CaseOut:
    with pool.connection() as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            """
            UPDATE cases SET case_no=%(case_no)s, title=%(title)s,
                   cause=%(cause)s, parties=%(parties)s, lawyer=%(lawyer)s,
                   remark=%(remark)s
             WHERE id=%(id)s RETURNING *
            """,
            {**payload.model_dump(), "id": case_id},
        ).fetchone()
        conn.commit()
    if not row:
        raise HTTPException(404, "案件不存在")
    return _row_to_case(row)


@router.delete("/{case_id}", status_code=204)
def remove_case(case_id: int) -> None:
    with pool.connection() as conn:
        # 显式 tuple_row：连接会被池复用，行工厂可能被上一个借用者改成 dict
        conn.row_factory = tuple_row
        rows = conn.execute(
            "SELECT id, stored_name FROM documents WHERE case_id=%s", (case_id,)
        ).fetchall()
        if not conn.execute("SELECT 1 FROM cases WHERE id=%s", (case_id,)).fetchone():
            raise HTTPException(404, "案件不存在")
        conn.execute("DELETE FROM cases WHERE id=%s", (case_id,))
        conn.commit()
    delete_case_files(rows)
