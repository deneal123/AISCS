"""Stage a verified replay input under a service-owned execution UUID."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import uuid
from pathlib import Path
from uuid import UUID


class ReplayInputStore:
    def __init__(self, root: Path):
        self.root = root

    def path(self, execution_id: UUID) -> Path:
        if not isinstance(execution_id, UUID):
            raise ValueError("Invalid execution ID")
        return self.root / str(execution_id) / "replay-input.bin"

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    async def put(self, execution_id: UUID, expected_sha256: str, chunks):
        if (not isinstance(expected_sha256, str)
                or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)):
            raise ValueError("Invalid input checksum")
        target = self.path(execution_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".replay-input-{uuid.uuid4().hex}.pending"
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary.open("xb") as stream:
                async for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise ValueError("Invalid input chunk")
                    size += len(chunk)
                    digest.update(chunk)
                    if await asyncio.to_thread(stream.write, chunk) != len(chunk):
                        raise OSError("Incomplete replay input write")
                await asyncio.to_thread(stream.flush)
                await asyncio.to_thread(os.fsync, stream.fileno())
            if digest.hexdigest() != expected_sha256:
                raise ValueError("Replay input checksum mismatch")
            try:
                # A hard link publishes atomically and fails rather than overwriting.
                os.link(temporary, target)
            except FileExistsError:
                if await asyncio.to_thread(self._digest, target) != expected_sha256:
                    raise ValueError("Execution already has a different replay input") from None
            return {"sha256": expected_sha256, "bytes": size}
        finally:
            temporary.unlink(missing_ok=True)

    def discard(self, execution_id: UUID, expected_sha256: str):
        """Remove only a matching service-owned input for this execution."""
        if (not isinstance(expected_sha256, str)
                or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)):
            raise ValueError("Invalid input checksum")
        target = self.path(execution_id)
        if not target.exists():
            return False
        if self._digest(target) != expected_sha256:
            raise ValueError("Replay input checksum mismatch")
        target.unlink()
        return True
