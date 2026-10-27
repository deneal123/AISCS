"""Owned raw Library reads; bounded storage transfer, no presigned URL or unpacking."""

import asyncio
import hashlib
import re
import tempfile
from typing import Any
from uuid import UUID

from service.infrastructure.storage.bounded_download import DownloadLimitExceeded
from service.models.key_value import ServiceType

MAX_LIBRARY_COPY_BYTES = 20 * 1024 * 1024


class LibraryReadFailure(Exception):
    def __init__(self, code="ide_library_unavailable"):
        self.code = code
        super().__init__(code)


async def read_library_bytes(repository: Any, storage: Any, user_id: UUID, file_id: UUID) -> bytes:
    try:
        row = await repository.fetch_user_file_by_id(user_id, file_id)
        if row is None or row.type != ServiceType.CHAT:
            raise LibraryReadFailure("ide_library_missing")
        download = getattr(storage, "download_file_stream", None)
        if not callable(download):
            raise LibraryReadFailure()
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as spool:
            async with asyncio.timeout(15):
                size = await download(
                    file_key=row.file_name, target=spool, max_bytes=MAX_LIBRARY_COPY_BYTES
                )
            if (
                type(size) is not int
                or not 0 <= size <= MAX_LIBRARY_COPY_BYTES
                or spool.tell() != size
            ):
                raise LibraryReadFailure()
            spool.seek(0)
            data = spool.read(MAX_LIBRARY_COPY_BYTES + 1)
        if len(data) != size:
            raise LibraryReadFailure()
        digest = getattr(row, "content_sha256", None)
        if digest and (
            type(digest) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or hashlib.sha256(data).hexdigest() != digest
        ):
            raise LibraryReadFailure("ide_library_integrity")
        return data
    except LibraryReadFailure:
        raise
    except DownloadLimitExceeded:
        raise LibraryReadFailure("ide_library_limit") from None
    except Exception:
        raise LibraryReadFailure() from None
