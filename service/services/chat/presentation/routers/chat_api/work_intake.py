"""Durable Library intake for the explicit Work Hub upload action."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi import HTTPException, UploadFile

from service.models.key_value import ServiceType
from service.services.files.application.file_saver_service import UploadIntentConflict
from service.settings import config

logger = logging.getLogger(__name__)

WORKSPACE_INTAKE_STATUSES = frozenset({"conflict", "locked", "expired", "unavailable"})


class WorkspaceIntakeDeferred(RuntimeError):
    """The Library commit succeeded while the temporary copy was deferred."""

    def __init__(self, status: str, revision: str = "") -> None:
        self.status = status if status in WORKSPACE_INTAKE_STATUSES else "unavailable"
        self.revision = str(revision or "")
        super().__init__(self.status)


def _safe_file(saved: Any, name: str) -> dict[str, str]:
    return {
        "file_id": str(saved.file_id),
        "name": name,
        "file_type": ServiceType.CHAT.value,
        "availability": "ready",
    }


async def persist_and_import_uploaded_file(
    *,
    file: UploadFile,
    user_id: Any,
    file_service: Any,
    import_workspace: Callable[[dict], Awaitable[dict | None]],
    upload_intent_id: UUID | None = None,
) -> dict:
    """Commit the durable source, then attempt one atomic Workspace import."""
    name = str(file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or len(name) > 1_000:
        raise HTTPException(status_code=400, detail="Укажите корректное имя файла")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Нельзя добавить пустой файл")
    max_bytes = int(config.agents.upload_max_bytes or 20 * 1024 * 1024)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="Файл превышает допустимый размер")

    save_options = {
        "user_id": user_id,
        "mode": ServiceType.CHAT,
        "file_name": name,
        "file_content": content,
    }
    if upload_intent_id is not None:
        save_options["upload_intent_id"] = upload_intent_id
    try:
        saved = await file_service.save(**save_options)
    except UploadIntentConflict as exc:
        raise HTTPException(status_code=409, detail="upload_intent_conflict") from exc
    except Exception as exc:  # Storage/database failures must not create phantom files.
        logger.warning(
            "workspace intake failure",
            extra={"component": "library", "failure_code": "persist_unavailable"},
        )
        raise HTTPException(
            status_code=503,
            detail="Не удалось сохранить файл. Повторите загрузку.",
        ) from exc

    safe_file = _safe_file(saved, name)
    try:
        source = await file_service.resolve_chat_library_import(
            user_id, saved.file_id, expiry_sec=120
        )
        result = await import_workspace(source)
        if not isinstance(result, dict):
            raise WorkspaceIntakeDeferred("unavailable")
    except WorkspaceIntakeDeferred as exc:
        return {
            "outcome": "library_saved",
            "workspace_status": exc.status,
            "revision": exc.revision,
            "file": safe_file,
        }
    except ValueError:
        return {
            "outcome": "library_saved",
            "workspace_status": "unavailable",
            "revision": "",
            "file": safe_file,
        }
    except Exception:
        # The durable Library write is already committed.  A source-signing,
        # coordinator, or sidecar failure must not turn that success into an
        # ambiguous whole-upload failure and provoke duplicate retries.
        logger.warning(
            "workspace intake failure",
            extra={"component": "workspace", "failure_code": "import_deferred"},
        )
        return {
            "outcome": "library_saved",
            "workspace_status": "unavailable",
            "revision": "",
            "file": safe_file,
        }

    revision = str(result.get("revision") or "")
    imported = int(result.get("imported") or 0)
    kept = int(result.get("kept") or 0)
    outcome = "imported" if imported else "kept" if kept else "library_saved"
    return {
        "outcome": outcome,
        "workspace_status": "ready" if outcome != "library_saved" else "unavailable",
        "revision": revision,
        "file": safe_file,
    }
