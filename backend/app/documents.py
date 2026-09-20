"""资料接口：本地保存原文件、解析结果和可恢复的 JSON 记录。"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

import anyio
from fastapi import APIRouter, BackgroundTasks, File, Form, Response, UploadFile
from fastapi.responses import FileResponse

from .errors import ApiError
from .settings import settings
from .content_models import WorkbenchResult
from .schemas import (
    DocumentDetail,
    DocumentListResponse,
    DocumentStatusResponse,
    ErrorResponse,
    FileType,
    ParsedDocumentResponse,
    WorkbenchData,
)
from .parser import ParsedDocument, parse_document
from .task_store import has_active_document_task, remove_document_tasks


router = APIRouter(
    prefix="/api/documents",
    tags=["documents"],
    responses={
        400: {"model": ErrorResponse, "description": "请求内容不支持"},
        404: {"model": ErrorResponse, "description": "资料不存在"},
        409: {"model": ErrorResponse, "description": "资料尚未完成解析"},
        413: {"model": ErrorResponse, "description": "文件超过大小上限"},
        422: {"model": ErrorResponse, "description": "请求参数不正确"},
        500: {"model": ErrorResponse, "description": "服务处理失败"},
    },
)

# 内存字典让接口查询简单；每条记录另存为 JSON，开发服务器重启后可恢复。
documents: dict[str, DocumentDetail] = {}
FILE_TYPES: dict[str, FileType] = {".pdf": "pdf", ".docx": "docx"}
CHUNK_SIZE = 1024 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
logger = logging.getLogger(__name__)


def get_document_file_path(document: DocumentDetail) -> Path:
    """磁盘文件名只由服务端生成的 UUID 和已校验类型决定。"""
    extension = ".pdf" if document.file_type == "pdf" else ".docx"
    return settings.uploads_path / f"{document.id}{extension}"


def get_document_record_path(document_id: str) -> Path:
    try:
        canonical_id = str(UUID(document_id))
    except ValueError as exc:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "找不到该资料") from exc
    if canonical_id != document_id:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "找不到该资料")
    return settings.uploads_path / f"{canonical_id}.json"


def _ensure_private_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        directory.chmod(0o700)


def _restrict_file_permissions(path: Path) -> None:
    # Windows inherits the parent directory ACL; POSIX storage should be readable
    # and writable only by the account running this local application.
    if os.name != "nt":
        path.chmod(0o600)


def get_parsed_result_paths(document_id: str) -> tuple[Path, Path]:
    """解析结果路径只接受规范 UUID，避免请求内容拼接出目录外路径。"""
    try:
        canonical_id = str(UUID(document_id))
    except ValueError as exc:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "找不到该资料") from exc
    if canonical_id != document_id:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "找不到该资料")

    return (
        settings.parsed_path / f"{canonical_id}.md",
        settings.parsed_path / f"{canonical_id}.json",
    )


def get_content_model_paths(document_id: str) -> tuple[Path, Path]:
    """返回归一化内容块和 Workbench 结果的本地 JSON 路径。"""
    _, _ = get_parsed_result_paths(document_id)
    canonical_id = str(UUID(document_id))
    return (
        settings.parsed_path / f"{canonical_id}.blocks.json",
        settings.parsed_path / f"{canonical_id}.workbench.json",
    )


def load_saved_documents() -> dict[str, DocumentDetail]:
    """恢复有效的本地记录；损坏或缺少原文件的记录不显示为可用资料。"""
    restored: dict[str, DocumentDetail] = {}
    for record_path in settings.uploads_path.glob("*.json"):
        try:
            document = DocumentDetail.model_validate_json(
                record_path.read_text(encoding="utf-8")
            )
            # 不信任文件内容中的 ID，避免它被用于拼接目录外的路径。
            canonical_id = str(UUID(document.id))
            if canonical_id != document.id:
                continue
            if not get_document_file_path(document).is_file():
                logger.warning(
                    "Skipping document record without source file: %s",
                    canonical_id,
                )
                continue
            restored[document.id] = document
        except (OSError, ValueError) as exc:
            logger.warning(
                "Skipping unreadable document record %s: %s",
                record_path.name,
                exc,
            )
    return restored


documents.update(load_saved_documents())


def validate_file_content(file_type: FileType, path: Path, header: bytes) -> None:
    """检查文件签名；DOCX 还必须是包含正文部件的 Office ZIP 包。"""
    if file_type == "pdf":
        if b"%PDF-" not in header[:1024]:
            raise ApiError(400, "INVALID_FILE_CONTENT", "文件内容不是有效的 PDF")
        return

    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
    except (BadZipFile, OSError):
        raise ApiError(400, "INVALID_FILE_CONTENT", "文件内容不是有效的 DOCX")

    expanded_size = 0
    for entry in entries:
        normalized_name = entry.filename.replace("\\", "/")
        archive_path = PurePosixPath(normalized_name)
        if (
            archive_path.is_absolute()
            or not archive_path.parts
            or ".." in archive_path.parts
            or ":" in archive_path.parts[0]
            or entry.flag_bits & 0x1
        ):
            raise ApiError(400, "INVALID_FILE_CONTENT", "DOCX 包含不安全或加密的文件项")
        expanded_size += entry.file_size
        if expanded_size > MAX_DOCX_UNCOMPRESSED_BYTES:
            raise ApiError(413, "FILE_TOO_LARGE", "DOCX 解压后的内容超过安全上限")

    required_parts = {"[Content_Types].xml", "word/document.xml"}
    if not required_parts.issubset(names):
        raise ApiError(400, "INVALID_FILE_CONTENT", "文件内容不是有效的 DOCX")


async def save_uploaded_file(
    file: UploadFile,
    file_type: FileType,
    document_id: str,
) -> int:
    """分块写入临时文件，校验成功后原子改名，避免留下半个文件。"""
    upload_dir = settings.uploads_path
    _ensure_private_directory(upload_dir)
    extension = ".pdf" if file_type == "pdf" else ".docx"
    target_path = upload_dir / f"{document_id}{extension}"
    temporary_path = upload_dir / f"{document_id}{extension}.part"
    total_size = 0
    header = bytearray()

    try:
        async with await anyio.open_file(temporary_path, "wb") as destination:
            _restrict_file_permissions(temporary_path)
            while chunk := await file.read(CHUNK_SIZE):
                total_size += len(chunk)
                if total_size > settings.max_upload_size_bytes:
                    limit_mb = settings.max_upload_size_mb
                    raise ApiError(
                        413,
                        "FILE_TOO_LARGE",
                        f"文件超过大小上限（{limit_mb} MB）",
                    )
                if len(header) < 1024:
                    header.extend(chunk[: 1024 - len(header)])
                await destination.write(chunk)

        if total_size == 0:
            raise ApiError(400, "EMPTY_FILE", "不能上传空文件")

        validate_file_content(file_type, temporary_path, bytes(header))
        os.replace(temporary_path, target_path)
        return total_size
    except BaseException:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove partial upload %s", temporary_path.name)
        raise


def save_document_record(document: DocumentDetail) -> None:
    """用临时文件加原子改名，避免服务器中断时留下半份 JSON 记录。"""
    record_path = get_document_record_path(document.id)
    _ensure_private_directory(record_path.parent)
    temporary_path = record_path.with_suffix(".json.part")
    try:
        temporary_path.write_text(
            document.model_dump_json(indent=2),
            encoding="utf-8",
        )
        _restrict_file_permissions(temporary_path)
        os.replace(temporary_path, record_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def save_parsed_results(document_id: str, parsed: ParsedDocument) -> None:
    """原子写入原生解析结果、归一化块和 Workbench JSON。"""
    markdown_path, json_path = get_parsed_result_paths(document_id)
    blocks_path, workbench_path = get_content_model_paths(document_id)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_private_directory(markdown_path.parent)
    markdown_temporary_path = markdown_path.with_suffix(".md.part")
    json_temporary_path = json_path.with_suffix(".json.part")
    blocks_temporary_path = blocks_path.with_suffix(".json.part")
    workbench_temporary_path = workbench_path.with_suffix(".json.part")

    try:
        markdown_temporary_path.write_text(parsed.markdown, encoding="utf-8")
        json_temporary_path.write_text(
            json.dumps(parsed.structured_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        blocks_temporary_path.write_text(
            parsed.parsed_blocks.model_dump_json(indent=2),
            encoding="utf-8",
        )
        workbench_temporary_path.write_text(
            parsed.workbench_result.model_dump_json(indent=2),
            encoding="utf-8",
        )
        for path in (
            markdown_temporary_path,
            json_temporary_path,
            blocks_temporary_path,
            workbench_temporary_path,
        ):
            _restrict_file_permissions(path)
        os.replace(markdown_temporary_path, markdown_path)
        os.replace(json_temporary_path, json_path)
        os.replace(blocks_temporary_path, blocks_path)
        os.replace(workbench_temporary_path, workbench_path)
    except BaseException:
        markdown_temporary_path.unlink(missing_ok=True)
        json_temporary_path.unlink(missing_ok=True)
        blocks_temporary_path.unlink(missing_ok=True)
        workbench_temporary_path.unlink(missing_ok=True)
        raise


def update_document_record(
    document: DocumentDetail,
    **changes: object,
) -> DocumentDetail:
    """先持久化状态，再更新内存索引，避免两处状态不一致。"""
    updated_document = document.model_copy(update=changes)
    save_document_record(updated_document)
    documents[updated_document.id] = updated_document
    return updated_document


def get_document_or_error(document_id: str) -> DocumentDetail:
    """几个接口都需要按编号查资料，因此把重复逻辑放在这里。"""
    document = documents.get(document_id)
    if document is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "找不到该资料")
    return document


@router.post(
    "",
    response_model=DocumentDetail,
    status_code=202,
    summary="接收并保存资料",
)
async def create_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="PDF 或 DOCX 文件"),
    notes: str | None = Form(default=None, max_length=1000),
):
    """保存原文件并同步解析；解析失败时保留文件并返回 failed 状态。"""
    stored_file: Path | None = None
    document_id: str | None = None
    document: DocumentDetail | None = None
    try:
        # 去掉客户端可能附带的路径，只把安全的原始名称用于展示。
        filename = (
            (file.filename or "unnamed")
            .replace("\\", "/")
            .rsplit("/", 1)[-1]
        )
        filename = filename or "unnamed"
        file_type = FILE_TYPES.get(Path(filename).suffix.lower())
        if file_type is None:
            raise ApiError(
                400, "UNSUPPORTED_FILE_TYPE", "目前只支持 PDF 或 DOCX 文件"
            )

        if file.size is not None and file.size > settings.max_upload_size_bytes:
            raise ApiError(
                413,
                "FILE_TOO_LARGE",
                f"文件超过大小上限（{settings.max_upload_size_mb} MB）",
            )

        document_id = str(uuid4())
        size_bytes = await save_uploaded_file(file, file_type, document_id)
        stored_file = (
            settings.uploads_path
            / f"{document_id}{Path(filename).suffix.lower()}"
        )
        document = DocumentDetail(
            id=document_id,
            filename=filename,
            file_type=file_type,
            size_bytes=size_bytes,
            upload_progress_percent=100,
            status="pending",
            processing_stage="queued",
            processing_progress_percent=0,
            created_at=datetime.now(timezone.utc),
            notes=notes,
        )
        save_document_record(document)
        documents[document.id] = document
    except BaseException:
        # 若 JSON 记录没能落盘，撤销刚刚保存的原文件，避免产生孤儿文件。
        if stored_file is not None:
            try:
                stored_file.unlink(missing_ok=True)
                if document_id is not None:
                    get_document_record_path(document_id).unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    "Could not remove unrecorded upload %s",
                    stored_file.name,
                )
        raise
    finally:
        await file.close()

    if document is None:
        raise RuntimeError("上传完成后没有生成资料记录")
    background_tasks.add_task(process_saved_document, document.id)
    return document


async def process_saved_document(document_id: str) -> None:
    """Parse a saved file in a worker thread and persist each task milestone."""
    document = documents.get(document_id)
    if document is None:
        return

    try:
        document = update_document_record(
            document,
            status="processing",
            processing_stage="parsing",
            processing_progress_percent=10,
            error_message=None,
        )
        source_path = get_document_file_path(document)
        parsed = await anyio.to_thread.run_sync(
            parse_document, source_path, document.id
        )
        if parsed.status == "partial_success":
            logger.warning("Docling returned a partial result: %s", document.id)
        document = update_document_record(
            document,
            processing_stage="saving",
            processing_progress_percent=90,
        )
        await anyio.to_thread.run_sync(save_parsed_results, document.id, parsed)
        update_document_record(
            document,
            status="completed",
            processing_stage="completed",
            processing_progress_percent=100,
            error_message=None,
        )
    except Exception as exc:
        # Persist a useful failure category without putting raw parser paths or
        # uploaded document text in the API response or logs.
        logger.error(
            "Document parsing failed: id=%s error_type=%s",
            document_id,
            type(exc).__name__,
        )
        failed_document = document.model_copy(
            update={
                "status": "failed",
                "processing_stage": "failed",
                "error_message": (
                    f"文件已保存，但解析失败（{type(exc).__name__}）。"
                    "请确认文件完整且未加密后重试。"
                ),
            }
        )
        try:
            save_document_record(failed_document)
        except OSError:
            logger.error("Could not persist failed document status: id=%s", document_id)
        documents[document_id] = failed_document


def recover_interrupted_documents() -> None:
    """Mark persisted local parse jobs as failed after an unclean process stop."""
    for document in list(documents.values()):
        if document.status not in {"pending", "processing"}:
            continue
        failed_document = document.model_copy(
            update={
                "status": "failed",
                "processing_stage": "failed",
                "error_message": "服务在解析完成前停止。原文件仍保留，可重新处理。",
            }
        )
        try:
            save_document_record(failed_document)
        except OSError:
            logger.error("Could not recover document state: id=%s", document.id)
        documents[document.id] = failed_document


@router.get("", response_model=DocumentListResponse, summary="查看资料列表")
async def list_documents():
    items = sorted(
        documents.values(),
        key=lambda document: document.created_at,
        reverse=True,
    )
    return DocumentListResponse(items=items, total=len(items))


@router.get("/{document_id}", response_model=DocumentDetail, summary="查看资料详情")
async def get_document(document_id: str):
    return get_document_or_error(document_id)


@router.get("/{document_id}/file", summary="预览或下载原始资料")
async def get_document_file(document_id: str):
    document = get_document_or_error(document_id)
    source_path = get_document_file_path(document)
    if not source_path.is_file():
        raise ApiError(404, "DOCUMENT_FILE_NOT_FOUND", "找不到该资料的原始文件")

    is_pdf = document.file_type == "pdf"
    return FileResponse(
        source_path,
        media_type=("application/pdf" if is_pdf else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        filename=document.filename,
        content_disposition_type="inline" if is_pdf else "attachment",
    )


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="查看处理状态",
)
async def get_document_status(document_id: str):
    document = get_document_or_error(document_id)
    return DocumentStatusResponse(
        id=document.id,
        upload_progress_percent=document.upload_progress_percent,
        status=document.status,
        processing_stage=document.processing_stage,
        processing_progress_percent=document.processing_progress_percent,
        error_message=document.error_message,
    )


@router.get(
    "/{document_id}/workbench",
    response_model=WorkbenchData,
    summary="查看工作台数据",
)
async def get_workbench(document_id: str):
    document = get_document_or_error(document_id)
    if document.status != "completed":
        return WorkbenchData(
            document=document,
            document_id=document.id,
            workbench_status="failed" if document.status == "failed" else "pending",
        )

    _, workbench_path = get_content_model_paths(document.id)
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
        logger.exception("Could not read Workbench result: %s", document.id)
        raise ApiError(
            500,
            "WORKBENCH_RESULT_UNREADABLE",
            "工作台结果无法读取",
        )

    return WorkbenchData.model_validate(
        {**result.model_dump(), "document": document.model_dump()}
    )


@router.get(
    "/{document_id}/parsed",
    response_model=ParsedDocumentResponse,
    summary="读取 Docling 解析结果",
)
async def get_parsed_document(document_id: str):
    document = get_document_or_error(document_id)
    if document.status != "completed":
        raise ApiError(
            409,
            "DOCUMENT_NOT_PROCESSED",
            "资料尚未成功解析，请先检查处理状态",
        )

    markdown_path, json_path = get_parsed_result_paths(document.id)
    if not markdown_path.is_file() or not json_path.is_file():
        raise ApiError(404, "PARSED_RESULT_NOT_FOUND", "找不到该资料的解析结果")

    try:
        markdown = markdown_path.read_text(encoding="utf-8")
        structured_data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Could not read parsed result: %s", document.id)
        raise ApiError(500, "PARSED_RESULT_UNREADABLE", "解析结果无法读取")

    return ParsedDocumentResponse(
        id=document.id,
        markdown=markdown,
        structured_data=structured_data,
    )


@router.post(
    "/{document_id}/regenerate",
    response_model=DocumentDetail,
    status_code=202,
    summary="重新解析并生成工作台结果",
)
async def regenerate_document(
    document_id: str,
    background_tasks: BackgroundTasks,
):
    document = get_document_or_error(document_id)
    if document.status in {"pending", "processing"} or has_active_document_task(document_id):
        raise ApiError(409, "DOCUMENT_TASK_ACTIVE", "该资料仍在处理中")
    source_path = get_document_file_path(document)
    if not source_path.is_file():
        raise ApiError(404, "DOCUMENT_FILE_NOT_FOUND", "找不到该资料的原始文件")

    document = update_document_record(
        document,
        status="pending",
        processing_stage="queued",
        processing_progress_percent=0,
        error_message=None,
    )
    background_tasks.add_task(process_saved_document, document.id)
    return document


@router.delete("/{document_id}", status_code=204, summary="删除资料记录")
async def delete_document(document_id: str):
    document = get_document_or_error(document_id)
    if document.status in {"pending", "processing"} or has_active_document_task(document_id):
        raise ApiError(409, "DOCUMENT_TASK_ACTIVE", "该资料仍在处理中，完成后再删除")
    # 原件、解析结果和记录都通过可信 UUID 生成路径。
    parsed_markdown_path, parsed_json_path = get_parsed_result_paths(document.id)
    parsed_blocks_path, workbench_path = get_content_model_paths(document.id)
    try:
        # 先删除原件；若 Windows 上文件仍被占用，保留其余记录供用户重试。
        get_document_file_path(document).unlink(missing_ok=True)
        parsed_markdown_path.unlink(missing_ok=True)
        parsed_json_path.unlink(missing_ok=True)
        parsed_blocks_path.unlink(missing_ok=True)
        workbench_path.unlink(missing_ok=True)
        get_document_record_path(document.id).unlink(missing_ok=True)
    except PermissionError as exc:
        raise ApiError(
            409,
            "DOCUMENT_FILE_IN_USE",
            "原文件正被其他程序使用，请关闭文件后重试删除",
        ) from exc
    remove_document_tasks(document_id)
    del documents[document_id]
    return Response(status_code=204)
