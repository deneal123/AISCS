"""Driver-facing container operations used by lifecycle services."""

from __future__ import annotations

from typing import Any

from domain.policy import WorkspacePolicy

from drivers import ComputeDriver, ContainerRef


class ContainerOperations:
    def __init__(self, driver: ComputeDriver) -> None:
        self._driver = driver

    @property
    def driver_name(self) -> str:
        return str(getattr(self._driver, "name", "unknown"))

    async def create(
        self, workspace_id: str, policy: WorkspacePolicy, labels: dict[str, str]
    ) -> ContainerRef:
        try:
            return await self._driver.create(workspace_id, policy, labels=labels)
        except TypeError:
            return await self._driver.create(workspace_id, policy)

    async def verify(self, ref: ContainerRef, policy: WorkspacePolicy) -> None:
        await self._driver.verify_isolation(ref, policy)

    async def destroy(self, ref: ContainerRef) -> None:
        await self._driver.destroy(ref)

    async def exec(
        self,
        ref: ContainerRef,
        command: str,
        *,
        timeout_sec: float,
        max_output_chars: int,
        stdin_payload: bytes | None = None,
    ) -> Any:
        if stdin_payload is not None:
            return await self._driver.exec_with_input(
                ref,
                command,
                payload=stdin_payload,
                timeout_sec=timeout_sec,
                max_output_chars=max_output_chars,
            )
        return await self._driver.exec(
            ref, command, timeout_sec=timeout_sec, max_output_chars=max_output_chars
        )

    async def list_managed(self) -> list[Any] | None:
        discover = getattr(self._driver, "list_managed", None)
        return None if discover is None else await discover()
