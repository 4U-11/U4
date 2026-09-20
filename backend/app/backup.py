"""ZIP backup and safe merge-restore for local course material data."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any
from uuid import UUID
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import anyio
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .documents import (
    documents,
    load_saved_documents,
    validate_file_content,
)
from .errors import ApiError
from .schemas import DocumentDetail
from .settings import settings


router = APIRouter(prefix="/api/backup", tags=["backup"])
logger = logging.getLogger(__name__)

BACKUP_FORMAT = "course-material-learning-assistant-backup"
BACKUP_VERSION = 1
MAX_ARCHIVE_SIZE = 2 * 1024 * 1024 * 1024
MAX_EXPANDED_SIZE = 2 * 1024 * 1024 * 1024
MAX_FILE_SIZE = 1024 * 1024 * 1024
MAX_FILES = 100_000
MAX_MANIFEST_SIZE = 8 * 1024 * 1024
COPY_CHUNK_SIZE = 1024 * 1024
HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")
PARSED_SUFFIXES = (".workbench.json", ".blocks.json", ".json", ".md")


def _data_files() -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    for folder_name, folder in (
        ("uploads", settings.uploads_path),
        ("parsed", settings.parsed_path),
    ):
        if not folder.exists():
            continue
        for path in folder.iterdir():
            if path.is_file() and not path.is_symlink() and not path.name.endswith(
                (".part", ".tmp", ".import.part")
            ) and path.name != ".gitkeep":
                archive_name = f"storage/{folder_name}/{path.name}"
                try:
                    _document_id_for_path(archive_name)
                except ValueError:
                    continue
                entries.append((archive_name, path))
    return sorted(entries, key=lambda item: item[0])


def _delete_temp_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove temporary backup archive")


@router.get("/export", summary="导出资料和处理结果 ZIP 备份")
def export_backup():
    entries = _data_files()
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="course-material-backup-", suffix=".zip"
        )
        os.close(descriptor)
        archive_path = Path(temporary_name)
        manifest_files: list[dict[str, Any]] = []
        with ZipFile(archive_path, "w", compression=ZIP_DEFLATED, compresslevel=3) as archive:
            for archive_name, source_path in entries:
                info = ZipInfo(archive_name)
                info.compress_type = ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                digest = hashlib.sha256()
                size = 0
                with source_path.open("rb") as source, archive.open(info, "w") as target:
                    while chunk := source.read(COPY_CHUNK_SIZE):
                        target.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                manifest_files.append(
                    {"path": archive_name, "size": size, "sha256": digest.hexdigest()}
                )
            manifest = {
                "format": BACKUP_FORMAT,
                "version": BACKUP_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "files": manifest_files,
            }
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
                compress_type=ZIP_DEFLATED,
            )
        download_name = f"course-material-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename=download_name,
            background=BackgroundTask(_delete_temp_file, archive_path),
        )
    except OSError as exc:
        try:
            archive_path.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass
        logger.exception("Could not create local backup")
        raise ApiError(500, "BACKUP_EXPORT_FAILED", "无法生成备份文件。") from exc


def _document_id_for_path(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    if (
        path.is_absolute()
        or "\\" in relative_path
        or ":" in relative_path
        or len(path.parts) != 3
        or path.parts[0] != "storage"
        or path.parts[1] not in {"uploads", "parsed"}
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Unsupported backup path")

    filename = path.name
    if path.parts[1] == "uploads":
        if not filename.endswith((".json", ".pdf", ".docx")):
            raise ValueError("Unsupported upload file")
        id_text = filename.rsplit(".", 1)[0]
    else:
        suffix = next((item for item in PARSED_SUFFIXES if filename.endswith(item)), None)
        if suffix is None:
            raise ValueError("Unsupported parsed file")
        id_text = filename[: -len(suffix)]

    canonical_id = str(UUID(id_text))
    if canonical_id != id_text:
        raise ValueError("Noncanonical document ID")
    return canonical_id


def _validate_manifest(
    archive: ZipFile,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    infos = archive.infolist()
    if len(infos) > MAX_FILES + 1:
        raise ValueError("Too many backup entries")
    names = [info.filename for info in infos]
    if len(names) != len(set(names)) or names.count("manifest.json") != 1:
        raise ValueError("Invalid backup inventory")
    manifest_info = next(info for info in infos if info.filename == "manifest.json")
    if manifest_info.file_size > MAX_MANIFEST_SIZE:
        raise ValueError("Backup manifest is too large")
    manifest = json.loads(archive.read(manifest_info).decode("utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != BACKUP_FORMAT
        or manifest.get("version") != BACKUP_VERSION
        or not isinstance(manifest.get("files"), list)
        or len(manifest["files"]) > MAX_FILES
    ):
        raise ValueError("Unsupported backup format")

    expected: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[str]] = {}
    total_expanded = 0
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid backup manifest entry")
        relative_path = item.get("path")
        size = item.get("size")
        digest = item.get("sha256")
        if (
            not isinstance(relative_path, str)
            or not isinstance(size, int)
            or size < 0
            or size > MAX_FILE_SIZE
            or not isinstance(digest, str)
            or not HASH_PATTERN.fullmatch(digest)
        ):
            raise ValueError("Invalid backup file metadata")
        document_id = _document_id_for_path(relative_path)
        expected[relative_path] = {"size": size, "sha256": digest}
        grouped.setdefault(document_id, []).append(relative_path)
        total_expanded += size
        if total_expanded > MAX_EXPANDED_SIZE:
            raise ValueError("Backup expands beyond the allowed size")
        archive_path = PurePosixPath(relative_path)
        if (
            archive_path.parts[1] == "uploads"
            and archive_path.suffix.lower() in {".pdf", ".docx"}
            and size > settings.max_upload_size_bytes
        ):
            raise ValueError("Course material exceeds the configured upload limit")

    actual_infos = {info.filename: info for info in infos if info.filename != "manifest.json"}
    if set(actual_infos) != set(expected):
        raise ValueError("Backup contents do not match the manifest")
    for filename, info in actual_infos.items():
        mode = info.external_attr >> 16
        if (
            info.is_dir()
            or stat.S_ISLNK(mode)
            or info.flag_bits & 0x1
            or info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
            or info.file_size != expected[filename]["size"]
        ):
            raise ValueError("Unsupported backup entry")
    return expected, grouped


def _stage_archive(
    archive: ZipFile,
    expected: dict[str, dict[str, Any]],
    staging_root: Path,
) -> None:
    for relative_path, metadata in expected.items():
        staged_path = staging_root.joinpath(*PurePosixPath(relative_path).parts)
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with archive.open(relative_path, "r") as source, staged_path.open("wb") as target:
            while chunk := source.read(COPY_CHUNK_SIZE):
                size += len(chunk)
                if size > metadata["size"]:
                    raise ValueError("Backup entry size does not match manifest")
                target.write(chunk)
                digest.update(chunk)
        if size != metadata["size"] or digest.hexdigest() != metadata["sha256"]:
            raise ValueError("Backup integrity check failed")


def _validate_document_groups(staging_root: Path, grouped: dict[str, list[str]]) -> None:
    for document_id, paths in grouped.items():
        upload_names = [PurePosixPath(name).name for name in paths if "/uploads/" in name]
        records = [name for name in upload_names if name == f"{document_id}.json"]
        sources = [
            name
            for name in upload_names
            if name in {f"{document_id}.pdf", f"{document_id}.docx"}
        ]
        if len(records) != 1 or len(sources) != 1:
            raise ValueError("Backup document is missing its record or source file")

        record_path = staging_root / "storage" / "uploads" / records[0]
        document = DocumentDetail.model_validate_json(record_path.read_text(encoding="utf-8"))
        if document.id != document_id:
            raise ValueError("Backup document ID mismatch")
        expected_type = "pdf" if sources[0].endswith(".pdf") else "docx"
        if document.file_type != expected_type:
            raise ValueError("Backup document type mismatch")
        source_path = staging_root / "storage" / "uploads" / sources[0]
        with source_path.open("rb") as source:
            header = source.read(1024)
        validate_file_content(expected_type, source_path, header)


def _merge_staged_documents(
    staging_root: Path,
    grouped: dict[str, list[str]],
) -> tuple[int, int]:
    installed: list[Path] = []
    imported = 0
    skipped = 0
    try:
        for document_id, paths in grouped.items():
            target_paths = [
                (settings.uploads_path if "/uploads/" in relative_path else settings.parsed_path)
                / PurePosixPath(relative_path).name
                for relative_path in paths
            ]
            if document_id in documents or any(path.exists() for path in target_paths):
                skipped += 1
                continue
            for relative_path in paths:
                archive_path = PurePosixPath(relative_path)
                target_dir = (
                    settings.uploads_path
                    if archive_path.parts[1] == "uploads"
                    else settings.parsed_path
                )
                target_dir.mkdir(parents=True, exist_ok=True)
                target_path = target_dir / archive_path.name
                staged_path = staging_root.joinpath(*archive_path.parts)
                temporary_path = target_path.with_name(
                    f".{target_path.name}.import.part"
                )
                try:
                    shutil.copyfile(staged_path, temporary_path)
                    os.replace(temporary_path, target_path)
                except BaseException:
                    temporary_path.unlink(missing_ok=True)
                    raise
                installed.append(target_path)
            imported += 1
    except BaseException:
        for path in installed:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not roll back a partially restored backup file")
        raise
    return imported, skipped


@router.post("/import", summary="导入 ZIP 备份并恢复资料")
async def import_backup(file: UploadFile = File(...)):
    archive_size = file.size
    if archive_size is None:
        file.file.seek(0, os.SEEK_END)
        archive_size = file.file.tell()
    await file.seek(0)
    if archive_size > MAX_ARCHIVE_SIZE:
        raise ApiError(413, "BACKUP_TOO_LARGE", "备份文件超过 2 GB 上限。")
    try:
        with ZipFile(file.file) as archive:
            expected, grouped = _validate_manifest(archive)
            if not grouped:
                raise ValueError("Backup contains no documents")
            with tempfile.TemporaryDirectory(prefix="course-material-restore-") as directory:
                staging_root = Path(directory)
                await anyio.to_thread.run_sync(
                    _stage_archive, archive, expected, staging_root
                )
                await anyio.to_thread.run_sync(
                    _validate_document_groups, staging_root, grouped
                )
                imported, skipped = await anyio.to_thread.run_sync(
                    _merge_staged_documents, staging_root, grouped
                )

        documents.update(load_saved_documents())
        return {
            "ok": True,
            "imported_documents": imported,
            "skipped_documents": skipped,
            "message": f"已恢复 {imported} 份资料，跳过重复资料 {skipped} 份。",
        }
    except ApiError:
        raise
    except (BadZipFile, UnicodeDecodeError, json.JSONDecodeError, ValueError, OSError) as exc:
        raise ApiError(
            400,
            "INVALID_BACKUP_ARCHIVE",
            "备份文件无效或已损坏，未导入任何资料。",
        ) from exc
    finally:
        await file.close()
