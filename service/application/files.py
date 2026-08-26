"""Revision-aware file operations over a sandbox command runner."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from domain.files import (
    BAD_PATTERN_MARKER,
    grep_command,
    list_command,
    parse_read,
    read_command,
    tree_command,
    write_command,
)

RunCommand = Callable[..., Awaitable[Any]]
Revision = Callable[[Any], Awaitable[str]]
Snapshot = Callable[[Any, str], Awaitable[dict[str, Any]]]


class FileConflict(Exception):
    pass


class FileWriteFailed(Exception):
    pass


class FileService:
    def __init__(self, run_command: RunCommand, revision: Revision, snapshot: Snapshot) -> None:
        self._run_command, self._revision, self._snapshot = run_command, revision, snapshot

    async def list(self, item: Any, path: str) -> dict[str, Any]:
        result = await self._run_command(item, list_command(item.policy.root, path))
        entries = []
        for line in (result.stdout or "").splitlines():
            fields = line.split("\t", 2)
            if len(fields) == 3:
                entries.append({"type": fields[0], "size": int(fields[1] or 0), "path": fields[2]})
        return {"entries": entries, "truncated": bool(result.truncated)}

    async def tree(self, item: Any, path: str) -> dict[str, Any]:
        result = await self._run_command(item, tree_command(item.policy.root, path))
        return {
            "entries": [line for line in (result.stdout or "").splitlines() if line],
            "truncated": bool(result.truncated),
            "revision": await self._revision(item),
            "recovered": bool(getattr(item, "recovered", False)),
        }

    async def read(self, item: Any, path: str) -> dict[str, Any]:
        result = await self._run_command(item, read_command(item.policy.root, path))
        content, truncated = parse_read(result.stdout)
        return {
            "content": content,
            "truncated": bool(truncated or result.truncated),
            "revision": await self._revision(item),
            "recovered": bool(getattr(item, "recovered", False)),
        }

    async def grep(self, item: Any, pattern: str, path: str) -> dict[str, Any]:
        if not pattern.strip():
            raise ValueError("pattern is required")
        result = await self._run_command(item, grep_command(item.policy.root, pattern, path))
        lines = (result.stdout or "").splitlines()
        if lines and lines[0].strip() == BAD_PATTERN_MARKER:
            raise ValueError("invalid search pattern")
        return {"matches": lines, "truncated": bool(result.truncated)}

    async def write(
        self,
        item: Any,
        *,
        path: str,
        content: str,
        expected_revision: str | None,
        snapshot_user_edit: bool,
    ) -> dict[str, Any]:
        if expected_revision and await self._revision(item) != expected_revision:
            raise FileConflict("workspace revision changed")
        command, body = write_command(item.policy.root, path, content)
        result = await self._run_command(item, command, stdin_payload=body)
        if "__OK__" not in (result.stdout or ""):
            raise FileWriteFailed("workspace write failed")
        if snapshot_user_edit:
            await self._snapshot(item, "user_edit")
        return {"path": path, "written": True, "revision": await self._revision(item)}
