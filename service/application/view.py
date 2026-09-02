"""Coherent read model for the workspace room.

The Work Hub needs tree, history and revision from one serialization point.
Reading those pieces through separate HTTP calls allowed a mutation to land
between them and made the browser combine different workspace generations.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from domain.files import git_log_command, parse_git_log, tree_command

RunCommand = Callable[..., Awaitable[Any]]
Revision = Callable[[Any], Awaitable[str]]


def _parse_tree(stdout: str | None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in (stdout or "").splitlines():
        fields = line.split("\t", 2)
        if len(fields) != 3:
            continue
        entries.append({"type": fields[0], "size": int(fields[1] or 0), "path": fields[2]})
    return entries


class WorkspaceViewService:
    """Build one bounded, revision-consistent room snapshot."""

    def __init__(self, run_command: RunCommand, revision: Revision) -> None:
        self._run_command = run_command
        self._revision = revision

    async def snapshot(self, item: Any, path: str = "") -> dict[str, Any]:
        tree = await self._run_command(item, tree_command(item.policy.root, path))
        history = await self._run_command(item, git_log_command(item.policy.root))
        revision = await self._revision(item)
        return {
            "entries": _parse_tree(tree.stdout),
            "history": parse_git_log(history.stdout),
            "truncated": bool(tree.truncated or history.truncated),
            "root": item.policy.root,
            "revision": revision,
            "recovered": bool(getattr(item, "recovered", False)),
        }
