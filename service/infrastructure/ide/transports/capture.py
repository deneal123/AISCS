"""Verified private runtime capture; never allocates, uploads or publishes a head."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from tempfile import SpooledTemporaryFile
from typing import BinaryIO
from uuid import UUID

from service.infrastructure.sidecar import SidecarError
from service.infrastructure.storage.bounded_download import settled_thread
from service.services.chat.domain.ide.checkpoints.blob import IdeCheckpointError
from service.services.chat.domain.ide.runtime import WorkspaceBinding


@dataclass(frozen=True, slots=True)
class CapturePolicy:
    """Mandatory caller limits, not an invented retention or user storage quota."""

    entries: int
    file_bytes: int
    total_bytes: int
    archive_bytes: int
    manifest_bytes: int
    depth: int

    def __post_init__(self):
        if (
            any(type(value) is not int or value < 1 for value in asdict(self).values())
            or not self.file_bytes <= self.total_bytes < 2**31
            or not self.manifest_bytes <= self.archive_bytes < 2**31
            or self.manifest_bytes > 16 * 1024 * 1024
            or self.entries > 65533
            or self.depth > 64
        ):
            raise IdeCheckpointError()


@dataclass(frozen=True, slots=True)
class RepositoryCapture:
    source: BinaryIO = field(repr=False)
    size: int
    sha256: str = field(repr=False)


@asynccontextmanager
async def capture_repository(
    client,
    user_id: UUID,
    binding: WorkspaceBinding,
    *,
    capability: str,
    limits: CapturePolicy,
) -> AsyncIterator[RepositoryCapture]:
    if binding.expires_at <= time.time():
        raise IdeCheckpointError("ide_checkpoint_runtime_not_ready")
    if not client.enabled or not isinstance(limits, CapturePolicy) or not capability:
        raise IdeCheckpointError("ide_checkpoint_capture_unavailable")
    payload = dict(
        user_id=str(user_id),
        token=binding.token,
        expected_expires_at=binding.expires_at,
        coordination_capability=capability,
        limits=asdict(limits),
    )
    with SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as source:
        try:
            async with (
                asyncio.timeout(40),
                client._client.request_binary(
                    f"/workspaces/{binding.workspace_id}/ide/capture",
                    json_body=payload,
                    max_bytes=limits.archive_bytes,
                    timeout=40,
                ) as reply,
            ):
                headers = reply.headers
                raw_size, sha = (
                    headers.get("content-length", ""),
                    headers.get("x-ide-capsule-sha256", ""),
                )
                if (
                    headers.get("content-type") != "application/octet-stream"
                    or headers.get("x-ide-capsule-version") != "1"
                    or not re.fullmatch(r"[1-9][0-9]{0,9}", raw_size)
                    or not re.fullmatch(r"[a-f0-9]{64}", sha)
                    or not 0 < int(raw_size) <= limits.archive_bytes
                ):
                    raise IdeCheckpointError("ide_checkpoint_integrity_failed")
                size, digest = 0, hashlib.sha256()
                async for chunk in reply.chunks:
                    size += len(chunk)
                    if size > int(raw_size):
                        raise IdeCheckpointError("ide_checkpoint_integrity_failed")
                    digest.update(chunk)
                    if await settled_thread(lambda chunk=chunk: source.write(chunk)) != len(chunk):
                        raise IdeCheckpointError("ide_checkpoint_integrity_failed")
                if size != int(raw_size) or not hmac.compare_digest(digest.hexdigest(), sha):
                    raise IdeCheckpointError("ide_checkpoint_integrity_failed")
            if binding.expires_at <= time.time():
                raise IdeCheckpointError("ide_checkpoint_runtime_not_ready")
            await settled_thread(lambda: source.seek(0))
        except IdeCheckpointError:
            raise
        except (SidecarError, TimeoutError, OSError, ValueError):
            raise IdeCheckpointError("ide_checkpoint_capture_unavailable") from None
        # No HTTP resources/operation lock remain during storage/DB handoff.
        yield RepositoryCapture(source, size, sha)
