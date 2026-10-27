"""Bounded IDE read projection. Private sidecar metadata is never forwarded."""

from __future__ import annotations

import hashlib
from typing import Any

READ_ERRORS = {
    "ide_path_forbidden": 403,
    "ide_file_missing": 404,
    "ide_file_changed": 409,
    "ide_file_unsupported": 422,
    "ide_generation_changed": 409,
    "ide_runtime_not_ready": 409,
    "ide_runtime_expired": 410,
    "ide_read_unavailable": 503,
}
MAX_READ_BYTES = 256 * 1024
MAX_TREE_ENTRIES = 400
_HIDDEN = frozenset({".git", "node_modules", "__pycache__", ".venv", ".mypy_cache"})


class IdeReadError(Exception):
    def __init__(self, code: str = "ide_read_unavailable") -> None:
        self.code = code if type(code) is str and code in READ_ERRORS else "ide_read_unavailable"
        super().__init__(self.code)


def validate_path(path: str, *, root_allowed: bool = False) -> str:
    if type(path) is not str or len(path) > 1024:
        raise IdeReadError("ide_path_forbidden")
    if not path and root_allowed:
        return path
    if (
        not path
        or "\\" in path
        or any(
            part in {"", ".", ".."}
            or part in _HIDDEN
            or part.startswith(".gpthub-")
            or not part.isprintable()
            for part in path.split("/")
        )
    ):
        raise IdeReadError("ide_path_forbidden")
    return path


def _size(value: Any) -> bool:
    return type(value) is int and 0 <= value <= 2**63 - 1


def project_tree(payload: dict, path: str) -> dict:
    entries, truncated = payload.get("entries"), payload.get("truncated")
    if type(entries) is not list or len(entries) > MAX_TREE_ENTRIES or type(truncated) is not bool:
        raise IdeReadError()
    rows, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise IdeReadError()
        relative = validate_path(entry.get("path"))
        kind, size = entry.get("type"), entry.get("size")
        incomplete = entry.get("incomplete", False)
        if (
            relative in seen
            or (path and not relative.startswith(path + "/"))
            or type(kind) is not str
            or kind not in {"file", "dir"}
            or not _size(size)
            or type(incomplete) is not bool
            or (kind == "dir" and size != 0)
            or (kind == "file" and incomplete)
        ):
            raise IdeReadError()
        seen.add(relative)
        rows.append({"path": relative, "type": kind, "size": size, "incomplete": incomplete})
    return {"entries": rows, "truncated": truncated}


def project_file(payload: dict, path: str) -> dict:
    kind, size = payload.get("kind"), payload.get("size")
    content, digest, truncated = (
        payload.get("content"),
        payload.get("digest"),
        payload.get("truncated"),
    )
    if (
        payload.get("path") != path
        or type(kind) is not str
        or kind not in {"text", "binary"}
        or not _size(size)
    ):
        raise IdeReadError()
    if type(truncated) is not bool:
        raise IdeReadError()
    if kind == "binary":
        if content is not None or digest is not None:
            raise IdeReadError()
    else:
        if type(content) is not str:
            raise IdeReadError()
        try:
            encoded = content.encode("utf-8")
        except UnicodeError:
            raise IdeReadError() from None
        if len(encoded) > MAX_READ_BYTES:
            raise IdeReadError()
        if truncated:
            if digest is not None or size <= MAX_READ_BYTES:
                raise IdeReadError()
        elif size != len(encoded) or digest != hashlib.sha256(encoded).hexdigest():
            raise IdeReadError()
    return {
        "path": path,
        "kind": kind,
        "size": size,
        "content": content,
        "digest": digest,
        "truncated": truncated,
    }
