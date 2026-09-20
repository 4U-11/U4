"""使用 Docling 把 PDF / DOCX 转换为 Markdown 和结构化 JSON。"""

from dataclasses import dataclass
import gc
from pathlib import Path
from threading import Lock
from typing import Any

from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.document_converter import DocumentConverter

from .content import build_content_models
from .content_models import ParsedBlockCollection, WorkbenchResult


@dataclass(frozen=True)
class ParsedDocument:
    """一次文档解析的结果。"""

    markdown: str
    structured_data: dict[str, Any]
    status: str
    parsed_blocks: ParsedBlockCollection
    workbench_result: WorkbenchResult


# 只允许解析项目第一版支持的两种格式。
_converter = DocumentConverter(
    allowed_formats=[InputFormat.PDF, InputFormat.DOCX]
)

# 多个请求共用一个 converter；锁让本地第一版的解析任务依次执行。
_converter_lock = Lock()


def parse_document(source_path: Path, document_id: str) -> ParsedDocument:
    """解析文件并生成 Markdown、Docling JSON 和 Workbench 内容模型。"""

    source_path = Path(source_path)

    if not source_path.is_file():
        raise FileNotFoundError(f"找不到待解析文件：{source_path.name}")

    with _converter_lock:
        result = _converter.convert(source_path, raises_on_error=False)

    if result.status not in {
        ConversionStatus.SUCCESS,
        ConversionStatus.PARTIAL_SUCCESS,
    }:
        status = result.status.value
        # 错误转换结果仍引用输入后端；Windows 上先释放它，避免原件暂时被锁定。
        del result
        gc.collect()
        raise RuntimeError(
            f"Docling 解析失败，状态为：{status}"
        )

    document = result.document
    parsed_blocks, workbench_result = build_content_models(document, document_id)

    return ParsedDocument(
        markdown=document.export_to_markdown(traverse_pictures=True),
        structured_data=document.export_to_dict(),
        status=result.status.value,
        parsed_blocks=parsed_blocks,
        workbench_result=workbench_result,
    )
