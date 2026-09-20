"""Docling 元素到应用内容模型的保守映射。"""

import re
from enum import Enum
from typing import Any

from docling_core.types.doc.document import DoclingDocument
from pydantic import BaseModel

from .content_models import (
    AssignmentCandidate,
    BoundingBox,
    CodeBlockRecord,
    ParsedBlock,
    ParsedBlockCollection,
    SourceLocation,
    WorkbenchResult,
)


_ASSIGNMENT_HEADING = re.compile(
    r"作业|课后题|练习题|作业要求|\bhomework\b|\bassignment\b|\bproblem\s*set\b|\bexercises?\b",
    re.IGNORECASE,
)

_LABEL_TO_KIND = {
    "title": "heading",
    "section_header": "heading",
    "text": "text",
    "paragraph": "text",
    "list_item": "list_item",
    "code": "code",
    "formula": "formula",
    "table": "table",
    "picture": "picture",
    "chart": "picture",
}


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _item_text(item: Any, document: DoclingDocument, kind: str) -> str | None:
    value = getattr(item, "text", None)
    if isinstance(value, str) and value:
        return value
    if kind == "table":
        try:
            return item.export_to_markdown(document)
        except (AttributeError, TypeError, ValueError):
            return None
    return value if isinstance(value, str) else None


def _source_locations(item: Any) -> list[SourceLocation]:
    locations: list[SourceLocation] = []
    for provenance in getattr(item, "prov", None) or []:
        bbox_data = _json_value(getattr(provenance, "bbox", None))
        bbox = BoundingBox.model_validate(bbox_data) if bbox_data else None
        charspan = getattr(provenance, "charspan", None)
        locations.append(
            SourceLocation(
                page_no=getattr(provenance, "page_no", None),
                bbox=bbox,
                charspan=tuple(charspan) if charspan is not None else None,
            )
        )
    return locations


def _metadata(item: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {"item_type": type(item).__name__}
    for attribute in (
        "content_layer",
        "formatting",
        "hyperlink",
        "captions",
        "references",
        "footnotes",
        "annotations",
    ):
        value = getattr(item, attribute, None)
        if value is not None:
            metadata[attribute] = _json_value(value)
    return metadata


def build_content_models(
    document: DoclingDocument,
    document_id: str,
) -> tuple[ParsedBlockCollection, WorkbenchResult]:
    """按 Docling 阅读顺序提取块、来源、代码及作业候选。"""

    blocks: list[ParsedBlock] = []
    heading_stack: list[tuple[int, str]] = []

    for order, (item, level) in enumerate(
        document.iterate_items(with_groups=False, traverse_pictures=True)
    ):
        label = str(_enum_value(getattr(item, "label", "other")))
        kind = _LABEL_TO_KIND.get(label, "other")
        text = _item_text(item, document, kind)
        if text is not None:
            text = text.strip()
            if not text:
                text = None

        if kind == "heading":
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            if text:
                heading_stack.append((level, text))
        else:
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()

        heading_path = [heading for _, heading in heading_stack]
        is_assignment_candidate = (
            kind in {"text", "list_item"}
            and text is not None
            and any(_ASSIGNMENT_HEADING.search(heading) for heading in heading_path)
        )
        semantic_role = None
        classification_source = None
        classification_confidence = None
        if kind in {"text", "list_item"}:
            semantic_role = "normal_text"
        if is_assignment_candidate:
            semantic_role = "assignment_candidate"
            classification_source = "assignment_heading_keyword"
            # The heading is an explicit clue, but does not confirm that every
            # following sentence is an instruction.
            classification_confidence = 0.75

        raw_text = getattr(item, "orig", None)
        raw_text = raw_text if isinstance(raw_text, str) else None
        code_language = getattr(item, "code_language", None)
        if code_language is not None:
            code_language = str(_enum_value(code_language))

        table_data = getattr(item, "data", None) if kind == "table" else None
        table_data = _json_value(table_data) if table_data is not None else None

        block = ParsedBlock(
            id=f"{document_id}:{order}",
            document_id=document_id,
            order=order,
            kind=kind,
            semantic_role=semantic_role,
            classification_source=classification_source,
            classification_confidence=classification_confidence,
            docling_label=label,
            docling_ref=getattr(item, "self_ref", None),
            heading_path=heading_path,
            text=text,
            original_text=raw_text,
            code_language=code_language,
            table_data=table_data,
            source=_source_locations(item),
            metadata=_metadata(item),
        )
        blocks.append(block)

    collection = ParsedBlockCollection(document_id=document_id, blocks=blocks)
    code_blocks = [
        CodeBlockRecord(
            id=f"{block.id}:code",
            block_id=block.id,
            code=block.text,
            language=block.code_language,
            source=block.source,
        )
        for block in blocks
        if block.kind == "code" and block.text
    ]
    assignment_candidates = [
        AssignmentCandidate(
            id=f"{block.id}:assignment",
            block_id=block.id,
            text=block.text,
            classification_source=block.classification_source or "",
            confidence=block.classification_confidence or 0.0,
            source=block.source,
        )
        for block in blocks
        if block.semantic_role == "assignment_candidate" and block.text
    ]

    workbench = WorkbenchResult(
        document_id=document_id,
        generated_at=collection.generated_at,
        parsed_blocks=blocks,
        code_blocks=code_blocks,
        assignment_candidates=assignment_candidates,
    )
    return collection, workbench
