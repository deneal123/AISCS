"""Transfer an owned, verified activity journal to a replay executor."""

from __future__ import annotations

import hashlib
import tempfile
from uuid import UUID

from service.infrastructure.storage.bounded_download import settled_thread
from service.services.simulations.inputs.replay_source import ReplaySource


class ReplayTransferError(ValueError):
    pass


async def stage_replay_input(storage, client, execution_id: UUID, source: ReplaySource) -> None:
    """Verify storage bytes before publishing an immutable, execution-scoped input.

    The source must come from owned_replay_source; no user-provided paths or URLs
    are accepted. Storage and HTTP transfers are bounded without buffering the
    whole artifact in memory. The temporary file is closed on every exit path.
    """
    if not isinstance(execution_id, UUID):
        raise ReplayTransferError("invalid_execution_id")
    with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as stream:
        size = await storage.download_file_stream(
            file_key=source.storage_key, target=stream, max_bytes=source.size
        )
        if size != source.size or stream.tell() != source.size:
            raise ReplayTransferError("source_size_mismatch")

        def checksum():
            stream.seek(0)
            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            stream.seek(0)
            return digest.hexdigest()

        if await settled_thread(checksum) != source.sha256:
            raise ReplayTransferError("source_checksum_mismatch")

        async def chunks():
            while chunk := await settled_thread(lambda: stream.read(1024 * 1024)):
                yield chunk

        response = await client.put(
            f"/v1/replay-inputs/{execution_id}", content=chunks(),
            headers={"X-Content-SHA256": source.sha256, "Content-Length": str(source.size)},
        )
        response.raise_for_status()
        try:
            receipt = response.json()
        except ValueError as exc:
            raise ReplayTransferError("invalid_executor_receipt") from exc
        if (not isinstance(receipt, dict) or receipt.get("sha256") != source.sha256
                or type(receipt.get("bytes")) is not int or receipt["bytes"] != source.size):
            raise ReplayTransferError("invalid_executor_receipt")
