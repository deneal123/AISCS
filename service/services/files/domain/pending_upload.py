"""Private, typed inventory for temporary direct-upload source objects."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PendingUploadObject:
    key: str
    modified_at: datetime
    etag: str
    size: int


@dataclass(frozen=True, slots=True)
class PendingUploadPage:
    objects: tuple[PendingUploadObject, ...]
    next_cursor: str | None


def pending_identity(key: str, prefix: str) -> tuple[UUID, UUID] | None:
    """Accept only the exact server-issued namespace; never normalize traversal."""
    if not isinstance(key, str) or not key.startswith(prefix) or not prefix.endswith("/"):
        return None
    parts = key[len(prefix) :].split("/")
    if len(parts) != 2:
        return None
    owner_hex, filename = parts
    stem, extension = PurePosixPath(filename).stem, PurePosixPath(filename).suffix
    if not extension or not extension[1:].isascii() or not extension[1:].isalnum():
        return None
    try:
        owner, file_id = UUID(hex=owner_hex), UUID(hex=stem)
    except ValueError:
        return None
    if not owner.int or not file_id.int or owner.hex != owner_hex or file_id.hex != stem:
        return None
    return owner, file_id
