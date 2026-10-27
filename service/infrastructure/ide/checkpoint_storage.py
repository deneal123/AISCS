"""Private checked blob transport, deliberately not exposed as a save endpoint.

The application must first commit an owned write intent and later CAS-publish a
repository head. A verified upload alone is NOT a saved repository revision.
No cleanup on an uncertain acknowledgement: the durable intent owner must
reconcile/collect unreferenced objects without racing a late commit.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from tempfile import SpooledTemporaryFile
from typing import BinaryIO

from service.infrastructure.storage.abstract_file_storage import AbstractFileStorage
from service.infrastructure.storage.bounded_download import (
    CHUNK_BYTES,
    DownloadLimitExceeded,
    copy_bounded,
    download_limit,
    settled_thread,
)
from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.runtime import RepositoryScope


def _verify(stream: BinaryIO, blob: CheckpointBlob) -> None:
    stream.seek(0)
    digest, size = hashlib.sha256(), 0
    while chunk := stream.read(CHUNK_BYTES):
        digest.update(chunk)
        size += len(chunk)
    if size != blob.size or not hmac.compare_digest(digest.hexdigest(), blob.sha256):
        raise IdeCheckpointError("ide_checkpoint_integrity_failed")
    stream.seek(0)


class IdeCheckpointStorage:
    def __init__(self, storage: AbstractFileStorage, *, max_bytes: int) -> None:
        self.storage = storage
        # Mandatory caller policy; this helper does not invent a user quota.
        self.max_bytes = download_limit(max_bytes)

    @property
    def namespace(self) -> str:
        value = self.storage.namespace_id
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise IdeCheckpointError("ide_checkpoint_storage_unavailable")
        return value

    def _key(self, scope: RepositoryScope, blob: CheckpointBlob) -> str:
        key = blob.key_for(scope)
        if blob.size > self.max_bytes:
            raise IdeCheckpointError()
        return key

    @asynccontextmanager
    async def open(self, scope: RepositoryScope, blob: CheckpointBlob) -> AsyncIterator[BinaryIO]:
        key = self._key(scope, blob)
        with SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as staged:
            try:
                copied = await self.storage.download_file_stream(
                    file_key=key, target=staged, max_bytes=blob.size
                )
                if type(copied) is not int or copied != blob.size:
                    raise IdeCheckpointError("ide_checkpoint_integrity_failed")
                await settled_thread(lambda: _verify(staged, blob))
            except DownloadLimitExceeded:
                raise IdeCheckpointError("ide_checkpoint_integrity_failed") from None
            except IdeCheckpointError:
                raise
            except Exception:
                raise IdeCheckpointError("ide_checkpoint_storage_unavailable") from None
            # Keep consumer exceptions outside the storage privacy boundary.
            yield staged

    async def put(self, scope: RepositoryScope, blob: CheckpointBlob, source: BinaryIO) -> None:
        key = self._key(scope, blob)
        with SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as staged:

            def freeze() -> None:
                source.seek(0)
                try:
                    copy_bounded(source, staged, blob.size)
                except ValueError:
                    raise IdeCheckpointError("ide_checkpoint_integrity_failed") from None
                _verify(staged, blob)

            try:
                # Upload an owned frozen copy, not a caller-mutable stream.
                await settled_thread(freeze)
                await self.storage.upload_file_stream(file_key=key, stream=staged, length=blob.size)
            except IdeCheckpointError:
                raise
            except Exception:
                raise IdeCheckpointError("ide_checkpoint_storage_unavailable") from None
        # Never acknowledge storage based only on the SDK upload receipt.
        async with self.open(scope, blob):
            pass

    async def discard(self, scope: RepositoryScope, blob: CheckpointBlob) -> None:
        """Only a committed retention owner may authorize this exact object key.

        The ledger must survive both success and unknown ACK; repeating this
        idempotent deletion must never recapture or republish the retired ID.
        """
        key = self._key(scope, blob)
        try:
            await self.storage.delete_file(file_key=key)
        except Exception:
            raise IdeCheckpointError("ide_checkpoint_cleanup_unavailable") from None
