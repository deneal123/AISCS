"""Recover only digest-bound workspace files using a fresh, owned Redis binding."""

from __future__ import annotations

import math
import re
import time
from pathlib import PurePosixPath
from typing import Any

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
    PreparedCheckpointInvalid,
)


def _live_expiry(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value > time.time()
    except OverflowError:
        return False


def validated_inventory(raw: Any) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > 10:
        raise PreparedCheckpointInvalid("Materialization unavailable")
    total, names = 0, set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256", "required"}:
            raise PreparedCheckpointInvalid("Materialization unavailable")
        path, size, digest = item["path"], item["size"], item["sha256"]
        if (
            not isinstance(path, str)
            or not 0 < len(path) <= 1000
            or "\\" in path
            or ":" in path
            or path.startswith("/")
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in path)
            or type(size) is not int
            or not 0 < size <= 8 * 1024 * 1024
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or type(item["required"]) is not bool
        ):
            raise PreparedCheckpointInvalid("Materialization unavailable")
        filename = PurePosixPath(path).name
        if filename in names:
            raise PreparedCheckpointInvalid("Materialization unavailable")
        names.add(filename)
        total += size
    if total > 8 * 1024 * 1024:
        raise PreparedCheckpointInvalid("Materialization unavailable")
    return raw


async def recover_workspace_files(
    *,
    request: Any,
    facts: dict,
    metadata: dict,
    file_service: Any,
    redis_client: Any,
) -> dict:
    from service.infrastructure.agents_client.agent_file_bridge import persist_generated_artifacts
    from service.infrastructure.agents_client.required_artifacts import verified_content
    from service.infrastructure.workspace_client import collect_artifacts, read_binding_state

    inventory = validated_inventory(facts.get("workspace_files", []))
    if not inventory:
        return metadata
    status, binding = await read_binding_state(redis_client, request.thread_id)
    if (
        status != "ready"
        or not isinstance(binding, dict)
        or binding.get("workspace_id") != facts["workspace_id"]
        or str(binding.get("user_id")) != str(request.user_id)
        or not _live_expiry(binding.get("expires_at"))
    ):
        raise JobStateUnavailable("Materialization unavailable")
    # No workspace allocation or stale token reuse; download itself checks owner.
    downloaded = await collect_artifacts(
        binding, [{**item, "required": True} for item in inventory]
    )
    if len(downloaded) != len(inventory):
        raise JobStateUnavailable("Materialization unavailable")
    by_name = {item["filename"]: item for item in downloaded}
    for expected in inventory:
        artifact = by_name.get(PurePosixPath(expected["path"]).name, {})
        if (
            verified_content(
                artifact.get("file_b64"), expected["size"], expected["sha256"], 8 * 1024 * 1024
            )
            is None
        ):
            raise JobStateUnavailable("Materialization unavailable")
    _, result = await persist_generated_artifacts(
        file_service=file_service,
        user_id=request.user_id,
        job_id=request.job_id,
        metadata={**metadata, "_pending_artifacts": downloaded},
    )
    names = {
        item.get("filename")
        for item in result.get("generated_files", [])
        if isinstance(item, dict) and item.get("file_id")
    }
    if any(PurePosixPath(item["path"]).name not in names for item in inventory):
        raise JobStateUnavailable("Materialization unavailable")
    return result
