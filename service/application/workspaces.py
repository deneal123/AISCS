"""Lifecycle-facing workspace operations, independent from HTTP transport."""

from __future__ import annotations

from typing import Any

from domain.policy import WorkspacePolicy

from application.lifecycle import Workspace, WorkspaceRegistry


class WorkspaceService:
    def __init__(self, registry: WorkspaceRegistry) -> None:
        self._registry = registry

    async def create(
        self, user_id: str, policy: WorkspacePolicy, *, ttl_sec: float
    ) -> tuple[Workspace, str]:
        return await self._registry.create(user_id, policy, ttl_sec=ttl_sec)

    def resolve(self, workspace_id: str, user_id: str, token: str) -> Workspace:
        return self._registry.get(workspace_id, user_id, token)

    async def destroy(self, workspace_id: str) -> None:
        await self._registry.destroy(workspace_id)

    async def update_policy(self, item: Workspace, update: dict[str, Any]) -> WorkspacePolicy:
        return await self._registry.update_policy(item, update)

    async def exec(self, item: Workspace, command: str) -> Any:
        async with self._registry.operation(item):
            return await self._registry.exec(item, command)

    async def run_raw(
        self,
        item: Workspace,
        command: str,
        *,
        max_output_chars: int,
        stdin_payload: bytes | None = None,
    ) -> Any:
        return await self._registry.exec_raw(
            item, command, max_output_chars=max_output_chars, stdin_payload=stdin_payload
        )
