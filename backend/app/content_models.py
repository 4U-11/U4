"""面向 Workbench 的解析块和结果数据模型。"""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


ContentKind = Literal[
    "heading",
    "text",
    "list_item",
    "code",
    "formula",
    "table",
    "picture",
    "other",
]
SemanticRole = Literal["normal_text", "assignment_candidate"]
WorkbenchStatus = Literal["pending", "ready", "failed"]


class BoundingBox(BaseModel):
    """Docling 页面坐标；保留坐标原点，不自行转换方向或单位。"""

    l: float
    t: float
    r: float
    b: float
    coord_origin: str


class SourceLocation(BaseModel):
    """从解析块回到 Docling 元素、页面和页面区域的位置线索。"""

    page_no: int | None = None
    bbox: BoundingBox | None = None
    charspan: tuple[int, int] | None = None


class ParsedBlock(BaseModel):
    """原文的一项结构化内容，kind 表示版面类型，semantic_role 表示业务候选。"""

    id: str
    document_id: str
    order: int = Field(ge=0)
    kind: ContentKind
    semantic_role: SemanticRole | None = None
    classification_source: str | None = None
    classification_confidence: float | None = Field(default=None, ge=0, le=1)
    docling_label: str
    docling_ref: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    text: str | None = None
    original_text: str | None = None
    code_language: str | None = None
    table_data: dict[str, Any] | None = None
    source: list[SourceLocation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParsedBlockCollection(BaseModel):
    """单份资料的归一化解析块集合。"""

    schema_version: str = "1.0"
    document_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    blocks: list[ParsedBlock] = Field(default_factory=list)


class TranslationRecord(BaseModel):
    """保留原文、译文、目标语言和安全的翻译处理状态。"""

    id: str
    block_id: str
    source_text: str
    translated_text: str | None = None
    target_language: str = "zh-CN"
    status: Literal["pending", "completed", "failed"] = "pending"
    method: Literal["libretranslate", "ai"] | None = None
    error_code: Literal[
        "TRANSLATION_SERVICE_UNAVAILABLE",
        "TRANSLATION_INVALID_OUTPUT",
        "TRANSLATION_FAILED",
        "AI_PROVIDER_UNAVAILABLE",
        "AI_RESPONSE_INVALID",
    ] | None = None


class CodeBlockRecord(BaseModel):
    """和解析块关联的代码及后续解释字段。"""

    id: str
    block_id: str
    code: str
    language: str | None = None
    explanation: str | None = None
    source: list[SourceLocation] = Field(default_factory=list)


class AssignmentCandidate(BaseModel):
    """由显式作业章节标题识别的候选要求，仍需后续确认或加工。"""

    id: str
    block_id: str
    text: str
    classification_source: str
    confidence: float = Field(ge=0, le=1)
    source: list[SourceLocation] = Field(default_factory=list)


class GuideStep(BaseModel):
    """后续 AI 作业拆解输出；Step 6 保留结构，初始结果为空。"""

    id: str
    order: int = Field(ge=0)
    title: str
    description: str
    source_block_ids: list[str] = Field(default_factory=list)


class WorkbenchResult(BaseModel):
    """可直接供 Workbench 使用并可持久化的版本化 JSON 数据。"""

    schema_version: str = "1.0"
    document_id: str
    workbench_status: WorkbenchStatus = "ready"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    parsed_blocks: list[ParsedBlock] = Field(default_factory=list)
    translations: list[TranslationRecord] = Field(default_factory=list)
    code_blocks: list[CodeBlockRecord] = Field(default_factory=list)
    assignment_candidates: list[AssignmentCandidate] = Field(default_factory=list)
    guide_steps: list[GuideStep] = Field(default_factory=list)
