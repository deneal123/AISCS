"""Verified owner-only artifact persistence and honest deferred delivery projection."""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from service.infrastructure.agents_client.ports import ANON_USER_UUID, resolve_user_uuid

DELIVERY_READY_REPLY = (
    "Конспект готов и сохранён в Библиотеке. Его можно скачать из карточки файла."
)
DELIVERY_DEFERRED_REPLY = (
    "Конспект сохранён в рабочем месте, но сохранить файл в Библиотеку не удалось. "
    "Откройте Работу: конспект остаётся там доступен."
)


def artifact_filename(item: dict) -> str:
    """Project a bounded basename consistently through collection and delivery."""
    for value in (item.get("filename"), item.get("path")):
        if not isinstance(value, str):
            continue
        name = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if (
            name not in {"", ".", ".."}
            and len(name) <= 255
            and not any(ord(char) < 32 or ord(char) == 127 for char in name)
        ):
            return name
    return "artifact"


def verified_content(encoded: str, size: int, digest: Any, limit: int) -> bytes | None:
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return None
    if size <= 0 or size > limit or len(encoded) > ((limit + 2) // 3) * 4:
        return None
    try:
        content = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError):
        return None
    if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
        return None
    return content


async def save_required(file_service, user_id, job_id: str, filename: str, content: bytes):
    """No admin-owner fallback; retries of the same job reuse one owned UserFile."""
    from service.models.key_value import ServiceType

    owner = resolve_user_uuid(user_id, anonymous_fallback=False)
    if owner is None or owner == ANON_USER_UUID:
        raise ValueError("invalid_owner")
    digest = hashlib.sha256(content).hexdigest()
    intent = uuid5(NAMESPACE_URL, f"workspace-artifact:{owner}:{job_id}:{filename}:{digest}")
    return await file_service.save(
        user_id=owner,
        mode=ServiceType.CHAT,
        file_name=filename,
        file_content=content,
        upload_intent_id=intent,
    )


def project_delivery(inventory: list[dict], metadata: dict) -> dict:
    required = [item for item in inventory if item.get("required")]
    if not required:
        return metadata
    names = {
        item.get("filename")
        for item in metadata.get("generated_files", [])
        if isinstance(item, dict) and item.get("file_id")
    }
    if any(artifact_filename(item) not in names for item in required):
        metadata["execution_status"] = "deferred"
        metadata["partial_failure"] = True
        metadata["step_errors"] = list(
            dict.fromkeys([*metadata.get("step_errors", []), "unavailable"])
        )
    return metadata


def delivery_reply(reply: str, metadata: dict, execution_result: dict) -> str:
    """Only the persisted server result may promise a downloadable required file."""
    inventory = execution_result.get("workspace_artifacts") or []
    if not any(isinstance(item, dict) and item.get("required") for item in inventory):
        return reply
    if metadata.get("execution_status") == "deferred":
        return DELIVERY_DEFERRED_REPLY
    return DELIVERY_READY_REPLY
