"""Pydantic 请求/响应模型。"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class CaseIn(BaseModel):
    case_no: str | None = Field(None, max_length=100, description="案号")
    title: str = Field(..., min_length=1, max_length=300, description="案件名称")
    cause: str | None = Field(None, max_length=200, description="案由")
    parties: str = Field(..., min_length=1, description="当事人，多个用换行或逗号分隔")
    lawyer: str = Field(..., min_length=1, max_length=100, description="承办律师")
    remark: str | None = None


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_no: str | None
    title: str
    cause: str | None
    parties: str
    lawyer: str
    remark: str | None
    created_at: datetime


class CaseDetail(CaseOut):
    documents: list["DocumentOut"] = []


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    filename: str
    page_count: int
    size_bytes: int
    status: str
    error: str | None
    uploaded_at: datetime
    indexed_at: datetime | None


class PageHit(BaseModel):
    document_id: int
    case_id: int
    case_no: str | None
    case_title: str
    filename: str
    page_no: int
    snippet: str
    rank: float


class SearchResponse(BaseModel):
    q: str
    page: int
    page_size: int
    total: int
    hits: list[PageHit]
