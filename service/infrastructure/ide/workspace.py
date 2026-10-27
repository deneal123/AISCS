"""Non-retrying private allocation transport with an explicit PDF history mode."""

from __future__ import annotations

import asyncio
import math
import re
import time
from typing import Any
from uuid import UUID

import httpx

from service.infrastructure.sidecar import SidecarClient, SidecarError
from service.services.chat.domain.ide.files import (
    READ_ERRORS,
    IdeReadError,
    project_file,
    project_tree,
    validate_path,
)
from service.services.chat.domain.ide.runtime import (
    RuntimeAttempt,
    RuntimeObservation,
    WorkspaceBinding,
)


class IdeWorkspaceClient:
    async def execute(self, user_id, binding, **kwargs):
        from service.infrastructure.ide.transports.console import execute_repository

        return await execute_repository(self, user_id, binding, **kwargs)

    async def restore(self, scope, attempt, blob, **kwargs):
        from service.infrastructure.ide.transports.restore import restore_repository

        return await restore_repository(self, scope, attempt, blob, **kwargs)

    def capture(self, user_id, binding, **kwargs):
        from service.infrastructure.ide.transports.capture import capture_repository

        return capture_repository(self, user_id, binding, **kwargs)

    async def move(self, user_id: UUID, binding: WorkspaceBinding, **kwargs: Any) -> dict[str, Any]:
        from service.infrastructure.ide.transports.move import move_repository

        return await move_repository(self, user_id, binding, **kwargs)

    async def git(self, user_id, binding, **kwargs):
        from service.infrastructure.ide.transports.git import git_repository

        return await git_repository(self, user_id, binding, **kwargs)

    async def write(self, user_id, binding, **kwargs):
        from service.infrastructure.ide.transports.write import write_repository

        return await write_repository(self, user_id, binding, **kwargs)

    def __init__(self, settings: Any, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.enabled = bool(
            settings.workspace_enabled and settings.workspace_url and settings.workspace_api_key
        )
        self._timeout = max(1.0, min(120.0, float(settings.workspace_timeout_sec)))
        self._ttl = float(settings.workspace_ttl_sec)
        self._client = SidecarClient(
            service="workspace",
            base_url=settings.workspace_url,
            api_key=settings.workspace_api_key,
            timeout=self._timeout,
            transport=transport,
        )

    async def allocation_ttl(self) -> int | None:
        """Static protocol preflight for the first explicit allocation only."""
        if not self.enabled or not math.isfinite(self._ttl) or self._ttl < 1:
            return None
        try:
            async with asyncio.timeout(3):
                body = await self._client.request_json("GET", "/health", timeout=3)
            contract = body.get("contract", {})
            if body.get("service") != "workspace" or not isinstance(contract, dict):
                return None
            protocol = contract.get("allocation_protocol")
            ceiling = contract.get("allocation_max_ttl_sec")
            if (
                type(protocol) is not int
                or protocol != 1
                or type(ceiling) is not int
                or not 1 <= ceiling <= 2**31 - 1
            ):
                return None
            return min(int(self._ttl), ceiling)
        except (SidecarError, TimeoutError, ValueError, TypeError, httpx.InvalidURL):
            return None

    async def observe(
        self,
        user_id: UUID,
        attempt: RuntimeAttempt,
        *,
        create: bool = False,
        initialize_history: bool = False,
    ) -> RuntimeObservation:
        if attempt.expires_at <= time.time():
            return RuntimeObservation("expired")
        if not self.enabled:
            return RuntimeObservation("unavailable")
        if type(initialize_history) is not bool:
            return RuntimeObservation("unavailable")
        allocation = {"allocation_id": str(attempt.allocation_id), "expires_at": attempt.expires_at}
        # PDF needs a baseline revision before its first fenced scaffold. The
        # history-enabled route receives the same persisted allocation identity;
        # it is not an alternative allocation or an IDE clone fallback.
        creation_path = "/workspaces" if initialize_history else "/workspaces/allocations"
        timeout = self._timeout if create else min(3.0, self._timeout)
        try:
            async with asyncio.timeout(timeout):
                body = await self._client.request_json(
                    "POST",
                    creation_path if create else "/workspaces/allocations/lookup",
                    json_body={"user_id": str(user_id), "allocation": allocation},
                    timeout=timeout,
                )
            if attempt.expires_at <= time.time():
                return RuntimeObservation("expired")
            if create and initialize_history and body.get("versioned") is not True:
                return RuntimeObservation("unavailable")
            return RuntimeObservation("ready", self._binding(body, attempt))
        except SidecarError as error:
            if error.code == "workspace_allocation_pending":
                return RuntimeObservation("pending")
            if error.code == "workspace_allocation_expired":
                return RuntimeObservation("expired")
            if error.code == "workspace_allocation_conflict":
                return RuntimeObservation("rejected")
            if create and error.code == "quota_exceeded":
                return RuntimeObservation("rejected", retry_allowed=True)
            if error.code == "workspace_not_found":
                return RuntimeObservation("unknown")
            return RuntimeObservation("unavailable")
        except (TimeoutError, ValueError, TypeError, httpx.InvalidURL):
            return RuntimeObservation("unavailable")

    @staticmethod
    def _binding(body: dict[str, Any], attempt: RuntimeAttempt) -> WorkspaceBinding:
        workspace_id, token = body.get("workspace_id"), body.get("token")
        policy = body.get("policy")
        if not isinstance(workspace_id, str) or not re.fullmatch(r"[a-f0-9]{32}", workspace_id):
            raise ValueError("invalid_allocation_binding")
        if not isinstance(token, str) or not re.fullmatch(r"[0-9]{1,12}\.[a-f0-9]{64}", token):
            raise ValueError("invalid_allocation_binding")
        if (
            type(body.get("expires_at")) is not int
            or body["expires_at"] != attempt.expires_at
            or body.get("root") != "/workspace"
            or not isinstance(policy, dict)
            or policy.get("network") != "none"
            or policy.get("read_only_root") is not True
        ):
            raise ValueError("invalid_allocation_binding")
        if not int(time.time()) <= int(token.partition(".")[0]) <= attempt.expires_at:
            raise ValueError("invalid_allocation_binding")
        return WorkspaceBinding(workspace_id, token, attempt.expires_at)

    async def read(
        self, user_id: UUID, binding: WorkspaceBinding, *, operation: str, path: str
    ) -> dict[str, Any]:
        if operation not in {"tree", "file"}:
            raise IdeReadError()
        path = validate_path(path, root_allowed=operation == "tree")
        if binding.expires_at <= time.time():
            raise IdeReadError("ide_runtime_expired")
        if not self.enabled:
            raise IdeReadError()
        try:
            async with asyncio.timeout(10):
                body = await self._client.request_json(
                    "POST",
                    f"/workspaces/{binding.workspace_id}/ide/{operation}",
                    json_body={"user_id": str(user_id), "token": binding.token, "path": path},
                    timeout=10,
                )
            return project_tree(body, path) if operation == "tree" else project_file(body, path)
        except SidecarError as error:
            code = error.code if error.code in READ_ERRORS else "ide_read_unavailable"
            raise IdeReadError(code) from None
        except (TimeoutError, ValueError, TypeError, httpx.InvalidURL):
            raise IdeReadError() from None
