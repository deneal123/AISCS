"""Private fresh-allocation restore handoff; the caller owns durable dispatch.

No saved-head selection, generation claim, storage download or user retention is
performed here. A lost reply permits lookup only, never a second upload.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from contextlib import aclosing
from dataclasses import asdict
from typing import BinaryIO

import httpx

from service.infrastructure.ide.transports.capture import CapturePolicy
from service.infrastructure.sidecar import SidecarError
from service.infrastructure.storage.bounded_download import settled_thread
from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.runtime import (
    RepositoryScope,
    RuntimeAttempt,
    RuntimeObservation,
)


async def restore_repository(
    client,
    scope: RepositoryScope,
    attempt: RuntimeAttempt,
    blob: CheckpointBlob,
    *,
    source: BinaryIO | None = None,
    limits: CapturePolicy | None = None,
) -> RuntimeObservation:
    blob.key_for(scope)
    if blob.size <= 0 or blob.size >= 2**31:
        raise IdeCheckpointError()
    if attempt.expires_at <= time.time():
        return RuntimeObservation("expired")
    if not client.enabled:
        return RuntimeObservation("unavailable")
    upload = source is not None
    if upload and (
        attempt.state != "dispatching"
        or not isinstance(limits, CapturePolicy)
        or blob.size > limits.archive_bytes
    ):
        raise IdeCheckpointError("ide_checkpoint_runtime_not_ready")
    metadata = {
        "user_id": str(scope.user_id),
        "allocation": {
            "allocation_id": str(attempt.allocation_id),
            "expires_at": attempt.expires_at,
        },
        "snapshot": {"size": blob.size, "sha256": blob.sha256},
        **({"limits": asdict(limits)} if upload and limits is not None else {}),
    }
    headers = {"X-IDE-Restore-Request": json.dumps(metadata, separators=(",", ":"))}
    if upload:
        headers.update(
            {"Content-Type": "application/octet-stream", "Content-Length": str(blob.size)}
        )
    timeout = 45.0 if upload else 3.0
    try:
        async with asyncio.timeout(timeout):
            if upload:
                assert source is not None
                await settled_thread(lambda: source.seek(0))
                async with aclosing(_chunks(source, blob)) as content:
                    body = await client._client.upload_binary_json(
                        "/workspaces/allocations/restore",
                        content=content,
                        headers=headers,
                        timeout=timeout,
                    )
            else:
                body = await client._client.upload_binary_json(
                    "/workspaces/allocations/restore/lookup",
                    content=b"",
                    headers=headers,
                    timeout=timeout,
                )
        if attempt.expires_at <= time.time():
            return RuntimeObservation("expired")
        receipt = body.get("restore_snapshot")
        if (
            not isinstance(receipt, dict)
            or set(receipt) != {"size", "sha256"}
            or type(receipt["size"]) is not int
            or receipt != metadata["snapshot"]
        ):
            raise IdeCheckpointError("ide_checkpoint_integrity_failed")
        return RuntimeObservation("ready", client._binding(body, attempt))
    except SidecarError as error:
        if error.code == "workspace_allocation_pending":
            return RuntimeObservation("pending")
        if error.code == "workspace_allocation_expired":
            return RuntimeObservation("expired")
        return RuntimeObservation("unavailable")
    except (TimeoutError, OSError, TypeError, ValueError, httpx.InvalidURL):
        return RuntimeObservation("unavailable")


async def _chunks(source: BinaryIO, blob: CheckpointBlob):
    size, digest = 0, hashlib.sha256()
    while chunk := await settled_thread(lambda: source.read(65536)):
        size += len(chunk)
        if size > blob.size:
            raise IdeCheckpointError("ide_checkpoint_integrity_failed")
        digest.update(chunk)
        yield chunk
    if size != blob.size or not hmac.compare_digest(digest.hexdigest(), blob.sha256):
        raise IdeCheckpointError("ide_checkpoint_integrity_failed")
