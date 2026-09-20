"""Step 7/8 processing endpoints for translation and structured AI tasks."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
import re

from fastapi import APIRouter, BackgroundTasks, Header
from pydantic import BaseModel, ConfigDict, Field

from .ai import (
    AIProcessingError,
    explain_code_blocks,
    extract_code,
    generate_guide_steps,
    translate_blocks,
)
from .content_models import CodeBlockRecord, GuideStep, TranslationRecord, WorkbenchResult
from .documents import (
    get_content_model_paths,
    get_document_or_error,
)
from .errors import ApiError
from .local_settings import get_saved_active_key
from .translation import (
    TranslationError,
    collect_variable_names,
    prepare_translation,
    translate_with_libretranslate,
)
from .task_store import (
    ProcessingTask,
    TaskKind,
    create_processing_task,
    get_document_task,
    has_active_document_task,
    update_processing_task,
)


router = APIRouter(
    prefix="/api/documents",
    tags=["document processing"],
)

TaskName = TaskKind
_KEY_PATTERN = re.compile(r"[\r\n\x00]")
_TRANSLATION_ERROR_CODES = {
    "TRANSLATION_SERVICE_UNAVAILABLE",
    "TRANSLATION_INVALID_OUTPUT",
    "TRANSLATION_FAILED",
    "AI_PROVIDER_UNAVAILABLE",
    "AI_RESPONSE_INVALID",
}


class ProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: TaskName
    target_language: str = Field(
        default="zh-CN",
        min_length=2,
        max_length=20,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$",
    )


def _normalized_user_key(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    key = value.strip()
    if len(key) > 4096 or _KEY_PATTERN.search(key):
        raise ApiError(400, "INVALID_USER_API_KEY", "本次请求中的 API Key 格式无效")
    return key


def _load_workbench(document_id: str) -> WorkbenchResult:
    _, workbench_path = get_content_model_paths(document_id)
    if not workbench_path.is_file():
        raise ApiError(
            404,
            "WORKBENCH_RESULT_NOT_FOUND",
            "找不到该资料的结构化工作台结果",
        )
    try:
        result = WorkbenchResult.model_validate_json(
            workbench_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        raise ApiError(
            500,
            "WORKBENCH_RESULT_UNREADABLE",
            "工作台结果无法读取",
        )
    if result.document_id != document_id:
        raise ApiError(
            500,
            "WORKBENCH_DOCUMENT_MISMATCH",
            "工作台结果与资料编号不匹配",
        )
    return result


def _save_workbench(result: WorkbenchResult) -> None:
    _, workbench_path = get_content_model_paths(result.document_id)
    workbench_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = workbench_path.with_suffix(".json.part")
    try:
        temporary_path.write_text(
            result.model_dump_json(indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, workbench_path)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise ApiError(
            500,
            "WORKBENCH_RESULT_SAVE_FAILED",
            "工作台结果无法保存，请稍后重试",
        ) from exc


def _translation_failure_code(code: str) -> str:
    return code if code in _TRANSLATION_ERROR_CODES else "TRANSLATION_FAILED"


async def _translate_workbench(
    result: WorkbenchResult,
    target_language: str,
    user_api_key: str | None,
) -> None:
    eligible = [
        block
        for block in result.parsed_blocks
        if block.kind in {"heading", "text", "list_item"} and block.text
    ]
    if not eligible:
        return

    variables = collect_variable_names(result.parsed_blocks)
    prepared = {
        block.id: prepare_translation(block.text or "", variables, target_language)
        for block in eligible
    }
    translated: dict[str, str] = {}
    failures: dict[str, str] = {}

    if user_api_key:
        try:
            ai_results = await translate_blocks(
                [
                    {"block_id": block.id, "text": prepared[block.id].text}
                    for block in eligible
                ],
                target_language,
                user_api_key,
            )
            for block_id, translated_text in ai_results.items():
                translated[block_id] = prepared[block_id].restore(translated_text)
        except AIProcessingError as exc:
            translated.clear()
            code = _translation_failure_code(exc.code)
            failures.update({block.id: code for block in eligible})
        except TranslationError as exc:
            translated.clear()
            failures.update({block.id: exc.code for block in eligible})
    else:
        for block in eligible:
            try:
                raw_translation = await translate_with_libretranslate(
                    prepared[block.id].text,
                    target_language,
                )
                translated[block.id] = prepared[block.id].restore(raw_translation)
            except TranslationError as exc:
                failures[block.id] = _translation_failure_code(exc.code)

    replacements: dict[tuple[str, str], TranslationRecord] = {}
    for block in eligible:
        source_text = block.text or ""
        error_code = failures.get(block.id)
        replacements[(block.id, target_language)] = TranslationRecord(
            id=f"{block.id}:translation:{target_language}",
            block_id=block.id,
            source_text=source_text,
            translated_text=translated.get(block.id),
            target_language=target_language,
            status="failed" if error_code else "completed",
            method="ai" if user_api_key else "libretranslate",
            error_code=error_code,
        )

    retained = [
        record
        for record in result.translations
        if (record.block_id, record.target_language) not in replacements
    ]
    result.translations = [*retained, *replacements.values()]


async def _extract_code_workbench(
    result: WorkbenchResult,
    document_id: str,
    user_api_key: str,
) -> None:
    source_blocks = [
        block
        for block in result.parsed_blocks
        if block.kind in {"text", "list_item", "table"} and block.text
    ]
    if not source_blocks:
        return

    extracted = await extract_code(
        [
            {"block_id": block.id, "text": block.text or ""}
            for block in source_blocks
        ],
        user_api_key,
    )
    source_by_id = {block.id: block for block in source_blocks}
    codes_by_id = {
        code.id: code
        for code in result.code_blocks
        if not code.id.startswith("ai-extract:")
    }
    for item in extracted:
        source = source_by_id[item.source_block_id]
        code_hash = hashlib.sha256(item.code.encode("utf-8")).hexdigest()[:12]
        record_id = f"ai-extract:{document_id}:{item.source_block_id}:{code_hash}"
        codes_by_id[record_id] = CodeBlockRecord(
            id=record_id,
            block_id=item.source_block_id,
            code=item.code,
            language=item.language,
            source=source.source,
        )
    result.code_blocks = list(codes_by_id.values())


async def _explain_code_workbench(
    result: WorkbenchResult,
    user_api_key: str | None,
) -> None:
    if not result.code_blocks:
        return
    explanations = await explain_code_blocks(
        [
            {"block_id": code.id, "text": code.code}
            for code in result.code_blocks
        ],
        user_api_key,
    )
    result.code_blocks = [
        code.model_copy(update={"explanation": explanations[code.id]})
        for code in result.code_blocks
    ]


async def _decompose_workbench(
    result: WorkbenchResult,
    document_id: str,
    user_api_key: str | None,
) -> None:
    if not result.assignment_candidates:
        result.guide_steps = []
        return
    generated = await generate_guide_steps(
        [
            {"block_id": item.block_id, "text": item.text}
            for item in result.assignment_candidates
        ],
        user_api_key,
    )
    candidate_block_ids = {
        item.block_id for item in result.assignment_candidates
    }
    result.guide_steps = [
        GuideStep(
            id=f"{document_id}:guide:{index}",
            order=index,
            title=step.title,
            description=step.description,
            source_block_ids=step.source_block_ids,
        )
        for index, step in enumerate(generated, start=1)
        if set(step.source_block_ids).issubset(candidate_block_ids)
    ]


@router.post(
    "/{document_id}/process",
    response_model=ProcessingTask,
    status_code=202,
    summary="翻译资料或运行 AI 学习处理",
)
async def process_document(
    document_id: str,
    request: ProcessRequest,
    background_tasks: BackgroundTasks,
    user_api_key_header: str | None = Header(default=None, alias="X-User-API-Key"),
):
    document = get_document_or_error(document_id)
    if document.status != "completed":
        raise ApiError(
            409,
            "DOCUMENT_NOT_PROCESSED",
            "资料尚未成功解析，请先检查处理状态",
        )

    user_api_key = _normalized_user_key(user_api_key_header)
    if user_api_key is None:
        user_api_key = get_saved_active_key()
    if request.task == "extract_code" and not user_api_key:
        raise ApiError(
            403,
            "USER_API_KEY_REQUIRED",
            "代码提取需要本次请求提供用户自己的 AI Key。",
        )

    if has_active_document_task(document_id):
        raise ApiError(409, "DOCUMENT_TASK_ACTIVE", "该资料已有处理任务正在运行")

    task = create_processing_task(document_id, request.task)
    background_tasks.add_task(
        _run_processing_task,
        task.id,
        document_id,
        request,
        user_api_key,
    )
    return task


@router.get(
    "/{document_id}/tasks/{task_id}",
    response_model=ProcessingTask,
    summary="查看翻译或 AI 任务状态",
)
async def get_processing_task(document_id: str, task_id: str):
    return get_document_task(document_id, task_id)


async def _run_processing_task(
    task_id: str,
    document_id: str,
    request: ProcessRequest,
    user_api_key: str | None,
) -> None:
    """Run one process task and persist the final result or retryable failure."""
    update_processing_task(task_id, status="processing", progress_percent=5)
    try:
        document = get_document_or_error(document_id)
        result = _load_workbench(document_id)
        if request.task == "translate":
            await _translate_workbench(
                result,
                request.target_language,
                user_api_key,
            )
        elif request.task == "extract_code":
            await _extract_code_workbench(result, document_id, user_api_key or "")
        elif request.task == "explain_code":
            await _explain_code_workbench(result, user_api_key)
        elif request.task == "decompose_tasks":
            await _decompose_workbench(result, document_id, user_api_key)

        result.generated_at = datetime.now(timezone.utc)
        result.workbench_status = "ready"
        _save_workbench(result)
        update_processing_task(task_id, status="completed", progress_percent=100)
    except AIProcessingError as exc:
        update_processing_task(
            task_id,
            status="failed",
            error_code=exc.code,
            error_message=exc.message,
        )
    except ApiError as exc:
        update_processing_task(
            task_id,
            status="failed",
            error_code=exc.code,
            error_message=exc.message,
        )
    except Exception as exc:
        # Provider credentials and document contents must not be written to logs.
        import logging

        logging.getLogger(__name__).error(
            "Document processing task failed: id=%s error_type=%s",
            task_id,
            type(exc).__name__,
        )
        update_processing_task(
            task_id,
            status="failed",
            error_code="PROCESSING_FAILED",
            error_message="处理任务失败，请检查服务配置后重试。",
        )
