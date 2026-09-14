"""Pydantic 请求/响应模型。"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

SECURITY_LEVELS = ("normal", "secret", "confidential")


class CaseIn(BaseModel):
    case_no: str | None = Field(None, max_length=100, description="案号")
    title: str = Field(..., min_length=1, max_length=300, description="案件名称")
    cause: str | None = Field(None, max_length=200, description="案由")
    parties: str = Field(..., min_length=1, description="当事人，多个用换行或逗号分隔")
    lawyer: str = Field(..., min_length=1, max_length=100, description="承办律师")
    remark: str | None = None
    security_level: str = Field("normal", description="保密级别 normal/secret/confidential")

    def normalized_level(self) -> str:
        level = (self.security_level or "normal").strip().lower()
        if level not in SECURITY_LEVELS:
            raise ValueError("保密级别必须是 normal / secret / confidential")
        return level


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_no: str | None
    title: str
    cause: str | None
    parties: str
    lawyer: str
    remark: str | None
    security_level: str
    created_at: datetime


class SecurityLevelIn(BaseModel):
    security_level: str = Field(..., description="normal/secret/confidential")


class FolderIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="目录名称")


class FolderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    name: str
    position: int
    doc_count: int = 0


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    folder_id: int | None = None
    folder_name: str | None = None
    filename: str
    page_count: int
    size_bytes: int
    status: str
    error: str | None
    retry_count: int = 0
    uploaded_at: datetime
    indexed_at: datetime | None


class UploadResult(DocumentOut):
    """上传响应：deduplicated=True 表示同案件下已存在相同内容的卷宗，
    本次未重复落盘，直接返回已有卷宗。"""
    deduplicated: bool = False


class MoveDocumentIn(BaseModel):
    folder_id: int | None = Field(None, description="目标目录，null=未分类")


class CaseDetail(CaseOut):
    folders: list[FolderOut] = []
    documents: list[DocumentOut] = []


class PageHit(BaseModel):
    document_id: int
    case_id: int
    case_no: str | None
    case_title: str
    security_level: str
    folder_id: int | None = None
    folder_name: str | None = None
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
