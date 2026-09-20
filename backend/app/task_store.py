"""Small persistent task registry for the local, single-process first release."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from .errors import ApiError
from .settings import settings


logger = logging.getLogger(__name__)
TaskKind = Literal["translate", "extract_code", "explain_code", "decompose_tasks"]
TaskStatus = Literal["pending", "processing", "completed", "failed"]


class ProcessingTask(BaseModel):
    """Persisted task state; never includes request headers or API credentials."""

    model_config = ConfigDict(extra="forbid")

    id: str
    document_id: str
    task: TaskKind
    status: TaskStatus = "pending"
    progress_percent: int = Field(default=0, ge=0, le=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_code: str | None = None
    error_message: str | None = None


_lock = RLock()
processing_tasks: dict[str, ProcessingTask] = {}


def _canonical_uuid(value: str) -> str:
    try:
        canonical = str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ApiError(404, "TASK_NOT_FOUND", "找不到该处理任务") from exc
    if canonical != value:
        raise ApiError(404, "TASK_NOT_FOUND", "找不到该处理任务")
    return canonical


def _task_path(task_id: str) -> Path:
    return settings.tasks_path / f"{_canonical_uuid(task_id)}.json"


def _ensure_private_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        directory.chmod(0o700)


def _persist(task: ProcessingTask) -> None:
    target = _task_path(task.id)
    _ensure_private_directory(target.parent)
    temporary = target.with_suffix(".json.part")
    try:
        temporary.write_text(task.model_dump_json(indent=2), encoding="utf-8")
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def load_processing_tasks() -> None:
    """Reload the task index from the local task directory."""
    restored: dict[str, ProcessingTask] = {}
    for path in settings.tasks_path.glob("*.json"):
        try:
            task = ProcessingTask.model_validate_json(path.read_text(encoding="utf-8"))
            if _canonical_uuid(task.id) != task.id or path.name != f"{task.id}.json":
                continue
            _canonical_uuid(task.document_id)
            restored[task.id] = task
        except (OSError, ValueError, ApiError) as exc:
            logger.warning("Skipping unreadable task record %s: %s", path.name, type(exc).__name__)
    with _lock:
        processing_tasks.clear()
        processing_tasks.update(restored)


def create_processing_task(document_id: str, task_name: TaskKind) -> ProcessingTask:
    _canonical_uuid(document_id)
    task = ProcessingTask(
        id=str(uuid4()),
        document_id=document_id,
        task=task_name,
    )
    with _lock:
        _persist(task)
        processing_tasks[task.id] = task
    return task


def update_processing_task(task_id: str, **changes: object) -> ProcessingTask:
    canonical_id = _canonical_uuid(task_id)
    with _lock:
        current = processing_tasks.get(canonical_id)
        if current is None:
            raise ApiError(404, "TASK_NOT_FOUND", "找不到该处理任务")
        updated = current.model_copy(
            update={"updated_at": datetime.now(timezone.utc), **changes}
        )
        _persist(updated)
        processing_tasks[canonical_id] = updated
        return updated


def get_document_task(document_id: str, task_id: str) -> ProcessingTask:
    canonical_document_id = _canonical_uuid(document_id)
    canonical_task_id = _canonical_uuid(task_id)
    with _lock:
        task = processing_tasks.get(canonical_task_id)
    if task is None or task.document_id != canonical_document_id:
        raise ApiError(404, "TASK_NOT_FOUND", "找不到该处理任务")
    return task


def has_active_document_task(document_id: str) -> bool:
    with _lock:
        return any(
            task.document_id == document_id
            and task.status in {"pending", "processing"}
            for task in processing_tasks.values()
        )


def remove_document_tasks(document_id: str) -> None:
    with _lock:
        task_ids = [
            task_id
            for task_id, task in processing_tasks.items()
            if task.document_id == document_id
        ]
        for task_id in task_ids:
            try:
                _task_path(task_id).unlink(missing_ok=True)
            except OSError:
                logger.error("Could not remove task record: id=%s", task_id)
            processing_tasks.pop(task_id, None)


def recover_interrupted_processing_tasks() -> None:
    """Make tasks interrupted by a process restart visibly retryable."""
    load_processing_tasks()
    for task in list(processing_tasks.values()):
        if task.status not in {"pending", "processing"}:
            continue
        update_processing_task(
            task.id,
            status="failed",
            error_code="TASK_INTERRUPTED",
            error_message="服务在任务完成前停止，请重新运行该任务。",
        )

