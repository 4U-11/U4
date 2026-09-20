"""接口的数据格式：FastAPI 用这些模型检查响应，并生成 /docs 文档。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .content_models import WorkbenchResult


# 状态先统一命名；接入解析后，再实现从 pending 到其他状态的变化。
DocumentStatus = Literal["pending", "processing", "completed", "failed"]
DocumentStage = Literal["uploading", "queued", "parsing", "saving", "completed", "failed"]
FileType = Literal["pdf", "docx"]


class DocumentSummary(BaseModel):
    """资料列表里的一条记录。"""

    id: str
    filename: str
    file_type: FileType
    size_bytes: int | None = Field(default=None, ge=0)
    # 该记录创建时，整个文件已成功接收并保存；传输中的实时百分比由前端显示。
    upload_progress_percent: int = Field(default=100, ge=0, le=100)
    status: DocumentStatus
    processing_stage: DocumentStage = "completed"
    processing_progress_percent: int = Field(default=100, ge=0, le=100)
    created_at: datetime


class DocumentDetail(DocumentSummary):
    """详情沿用列表字段，再补上备注和处理失败的原因。"""

    notes: str | None = None
    error_message: str | None = None


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    total: int


class DocumentStatusResponse(BaseModel):
    id: str
    upload_progress_percent: int = Field(default=100, ge=0, le=100)
    status: DocumentStatus
    processing_stage: DocumentStage = "completed"
    processing_progress_percent: int = Field(default=100, ge=0, le=100)
    error_message: str | None = None


class WorkbenchData(WorkbenchResult):
    """带资料详情的 Workbench 结构化结果。"""

    document: DocumentDetail


class ParsedDocumentResponse(BaseModel):
    """Docling 生成的 Markdown 与原生结构化文档数据。"""

    id: str
    markdown: str
    structured_data: dict[str, Any]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
