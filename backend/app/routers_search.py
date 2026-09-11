"""全文检索接口：跨卷宗按页检索，返回高亮摘要并按相关度排序。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row

from .config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, SNIPPET_RADIUS
from .db import pool
from .models import PageHit, SearchResponse
from .permissions import current_role
from .search import build_tsquery, highlight_terms, make_snippet

router = APIRouter(prefix="/api/search", tags=["search"])

# 各角色可检索到正文的保密级别
_VIEW_LEVELS = {
    "secretary": ("normal",),
    "lawyer": ("normal", "secret"),
    "partner": ("normal", "secret", "confidential"),
}

SEARCH_SQL = """
    SELECT dp.document_id, dp.page_no, dp.raw_text,
           d.case_id, d.folder_id, f.name AS folder_name,
           c.case_no, c.title AS case_title, c.security_level,
           d.filename,
           ts_rank_cd(dp.tsv, to_tsquery('simple', %(tsq)s)) AS rank
      FROM document_pages dp
      JOIN documents d ON d.id = dp.document_id
      JOIN cases c     ON c.id = d.case_id
      LEFT JOIN folders f ON f.id = d.folder_id
     WHERE d.status = 'indexed'
       AND c.security_level = ANY(%(levels)s)
       AND dp.tsv @@ to_tsquery('simple', %(tsq)s)
       {case_filter}
       {folder_filter}
     ORDER BY rank DESC, dp.document_id, dp.page_no
     LIMIT %(limit)s OFFSET %(offset)s
"""

COUNT_SQL = """
    SELECT count(*) AS n
      FROM document_pages dp
      JOIN documents d ON d.id = dp.document_id
      JOIN cases c     ON c.id = d.case_id
     WHERE d.status = 'indexed'
       AND c.security_level = ANY(%(levels)s)
       AND dp.tsv @@ to_tsquery('simple', %(tsq)s)
       {case_filter}
       {folder_filter}
"""


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, description="检索关键词，多段空格分隔为 AND"),
    case_id: int | None = Query(None, description="限定案件范围"),
    folder_id: int | None = Query(None, description="限定目录范围，0=未分类"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    role: str = Depends(current_role),
) -> SearchResponse:
    tsq = build_tsquery(q)
    if not tsq:
        return SearchResponse(q=q, page=page, page_size=page_size, total=0, hits=[])

    case_filter = "AND d.case_id = %(case_id)s" if case_id else ""
    if folder_id is None:
        folder_filter = ""
    elif folder_id == 0:
        folder_filter = "AND d.folder_id IS NULL"
    else:
        folder_filter = "AND d.folder_id = %(folder_id)s"

    params = {
        "tsq": tsq,
        "levels": list(_VIEW_LEVELS[role]),
        "case_id": case_id,
        "folder_id": folder_id,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }

    with pool.connection() as conn:
        conn.row_factory = dict_row
        if case_id:
            case = conn.execute(
                "SELECT security_level FROM cases WHERE id=%s", (case_id,)
            ).fetchone()
            if not case:
                raise HTTPException(404, "案件不存在")
            if case["security_level"] not in _VIEW_LEVELS[role]:
                raise HTTPException(403, "您的角色无权检索该案件的卷宗内容")
        total = conn.execute(
            COUNT_SQL.format(case_filter=case_filter, folder_filter=folder_filter),
            params,
        ).fetchone()["n"]
        rows = conn.execute(
            SEARCH_SQL.format(case_filter=case_filter, folder_filter=folder_filter),
            params,
        ).fetchall()

    terms = highlight_terms(q)
    hits = [
        PageHit(
            document_id=r["document_id"],
            case_id=r["case_id"],
            case_no=r["case_no"],
            case_title=r["case_title"],
            security_level=r["security_level"],
            folder_id=r["folder_id"],
            folder_name=r["folder_name"],
            filename=r["filename"],
            page_no=r["page_no"],
            snippet=make_snippet(r["raw_text"], terms, radius=SNIPPET_RADIUS),
            rank=float(r["rank"]),
        )
        for r in rows
    ]
    return SearchResponse(q=q, page=page, page_size=page_size, total=total, hits=hits)
