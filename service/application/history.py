"""Revision and Git-history operations for an isolated workspace."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from domain.files import git_commit_command, git_head_command

SAFE_SNAPSHOT_TYPES = frozenset(
    {"agent_run", "import", "revert", "user_edit", "document_scaffold", "document_profile"}
)
RunCommand = Callable[..., Awaitable[Any]]


class HistoryService:
    def __init__(self, run_command: RunCommand) -> None:
        self._run_command = run_command

    async def revision(self, item: Any) -> str:
        result = await self._run_command(item, git_head_command(item.policy.root))
        value = (result.stdout or "").strip()
        return "" if value in {"__NO_GIT__", "__NO_REPO__", "__EMPTY__"} else value

    async def snapshot(self, item: Any, snapshot_type: str) -> dict[str, Any]:
        safe_type = snapshot_type if snapshot_type in SAFE_SNAPSHOT_TYPES else "agent_run"
        result = await self._run_command(item, git_commit_command(item.policy.root, safe_type))
        output = result.stdout or ""
        return {
            "committed": "__OK__" in output,
            "reason": next(
                (
                    marker
                    for marker in ("__NO_CHANGES__", "__NO_GIT__", "__NO_REPO__", "__FAILED__")
                    if marker in output
                ),
                "",
            )
            .strip("_")
            .lower(),
        }
