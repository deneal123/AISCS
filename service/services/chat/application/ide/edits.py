"""Repository-owned leases/writes, never a legacy thread workspace or automatic Git snapshot."""

from __future__ import annotations

import re
import time
from typing import Any
from uuid import UUID

from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.application.workspace_collaboration import (
    CollaborationConflict,
    CollaborationError,
    WorkspaceCollaborationStore,
    mint_capability,
    verify_capability,
)
from service.services.chat.domain.ide.edits import IdeEditError
from service.services.chat.domain.ide.files import validate_path
from service.services.chat.domain.ide.runtime import (
    RepositoryScope,
    ResolvedRuntime,
    generation_tag,
)


def validate_ide_session(session: str | None) -> str:
    if type(session) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", session):
        raise IdeEditError("ide_edit_session_required")
    return session


def _conflict(error: CollaborationConflict) -> IdeEditError:
    code = "ide_command_busy" if error.code == "ide_command_busy" else "ide_edit_lease_changed"
    return IdeEditError(code)


class IdeEditService:
    def __init__(self, runtime: IdeRuntimeService, redis: Any):
        self.runtime, self.redis = runtime, redis

    async def move(
        self,
        scope: RepositoryScope,
        *,
        generation: str,
        session: str | None,
        path: str,
        destination: str,
        expected_digest: str | None,
        fence: int,
        destination_fence: int,
    ) -> dict[str, Any]:
        path, destination = validate_path(path), validate_path(destination)
        if path == destination:
            raise IdeEditError("ide_file_changed")
        if destination.startswith(path + "/"):
            raise IdeEditError("ide_path_forbidden")
        try:
            resolved, capability, store = await self._context(scope, generation, session)
            verified = verify_capability(capability)
            await store.preflight(verified, mutation="write", path=path, fence=fence)
            await store.preflight(
                verified, mutation="write", path=destination, fence=destination_fence
            )
            await self._current(scope, resolved)
            result = await self.runtime.client.move(
                scope.user_id,
                resolved.binding,
                path=path,
                destination=destination,
                expected_digest=expected_digest,
                capability=capability,
                fence=fence,
                destination_fence=destination_fence,
            )
            await self._current(scope, resolved)
            return {"repository_id": str(scope.repository_id), "generation": generation, **result}
        except CollaborationConflict as error:
            raise _conflict(error) from None
        except CollaborationError:
            raise IdeEditError() from None

    async def git(
        self,
        scope: RepositoryScope,
        *,
        generation: str,
        session: str | None,
        operation: str,
        origin: str = "",
        branch: str = "",
        clone_intent_id: UUID | None = None,
    ) -> dict[str, Any]:
        from service.infrastructure.ide.transports.git_fetch import fetch_pack, parse_origin

        try:
            resolved, capability, store = await self._context(scope, generation, session)
            await store.preflight(verify_capability(capability), mutation="snapshot")
            pack, commit = b"", ""
            clone_policy = {}
            if operation == "clone":
                clone_destination = await self.runtime.repository.is_clone_destination(
                    **scope.params()
                )
                if clone_destination:
                    if clone_intent_id is None:
                        # Inspection/another browser must not bypass an earlier
                        # uncertain dispatch through the legacy Git endpoint.
                        raise IdeEditError("ide_git_conflict")
                    if not await self.runtime.repository.clone_dispatch_owned(
                        **scope.params(), intent_id=clone_intent_id
                    ):
                        raise IdeEditError("ide_git_unconfirmed")
                elif clone_intent_id is not None:
                    raise IdeEditError("ide_git_unconfirmed")
                starter = await self.runtime.repository.is_onboarding_owned(**scope.params())
                if starter is None:
                    raise IdeRepositoryNotFound
                if starter is True:
                    clone_policy["replace_pristine_starter"] = True
                origin = parse_origin(origin)
                # Definite user data can reject this destination before downloading
                # a pack that will only be downloaded again for an isolated clone.
                # Empty reads do NOT authorize replacement: the runtime still
                # performs its locked, no-follow pristine-seed check at publication.
                tree = await self.runtime.client.read(
                    scope.user_id, resolved.binding, operation="tree", path=""
                )
                await self._current(scope, resolved)
                if tree["entries"]:
                    raise IdeEditError("ide_git_not_empty")
                pack, branch, commit = await fetch_pack(origin, branch)
            await self._current(scope, resolved)
            result = await self.runtime.client.git(
                scope.user_id,
                resolved.binding,
                operation=operation,
                capability=capability,
                branch=branch or "main",
                origin=origin,
                commit=commit,
                pack=pack,
                **clone_policy,
            )
            await self._current(scope, resolved)
            return {"repository_id": str(scope.repository_id), "generation": generation, **result}
        except CollaborationConflict as error:
            raise _conflict(error) from None
        except CollaborationError:
            raise IdeEditError() from None

    async def _context(
        self, scope: RepositoryScope, generation: str, session: str | None
    ) -> tuple[ResolvedRuntime, str, WorkspaceCollaborationStore]:
        session = validate_ide_session(session)
        resolved = await self.runtime.resolve(scope)
        if generation != generation_tag(resolved.attempt):
            raise IdeEditError("ide_generation_changed")
        binding = resolved.binding
        capability = mint_capability(
            binding.workspace_id,
            role="ui",
            actor_seed=f"{scope.user_id}:{session}",
            expires_at=binding.expires_at,
        )
        store = WorkspaceCollaborationStore(
            self.redis,
            workspace_id=binding.workspace_id,
            expires_at=binding.expires_at,
            mutation_guard=self.runtime.mutation_guard,
        )
        return resolved, capability, store

    async def _current(self, scope: RepositoryScope, resolved: ResolvedRuntime) -> None:
        current = await self.runtime.runtime.get_owned(scope)
        if current is None:
            raise IdeRepositoryNotFound
        if current.allocation_id != resolved.attempt.allocation_id:
            raise IdeEditError("ide_generation_changed")
        if current.expires_at <= time.time():
            raise IdeEditError("ide_runtime_expired")
        if current.state != "ready":
            raise IdeEditError("ide_runtime_not_ready")

    async def lease(
        self,
        scope: RepositoryScope,
        *,
        path: str,
        generation: str,
        session: str | None,
        action: str,
        fence: int | None,
    ) -> dict[str, Any]:
        path = validate_path(path)
        try:
            resolved, raw, store = await self._context(scope, generation, session)
            capability = verify_capability(raw)
            if action == "acquire":
                result = (await store.acquire_lease(capability, path)).public()
            elif action == "renew" and fence is not None:
                result = (await store.renew_lease(capability, path, fence)).public()
            elif action == "release" and fence is not None:
                result = {"released": await store.release_lease(capability, path, fence)}
            else:
                raise IdeEditError("ide_edit_lease_changed")
            await self._current(scope, resolved)
            return {"repository_id": str(scope.repository_id), "generation": generation, **result}
        except CollaborationConflict as error:
            raise _conflict(error) from None
        except CollaborationError:
            raise IdeEditError() from None

    async def write(
        self,
        scope: RepositoryScope,
        *,
        path: str,
        generation: str,
        session: str | None,
        fence: int,
        operation: str,
        content: str,
        expected_digest: str | None,
    ) -> dict[str, Any]:
        path = validate_path(path)
        try:
            resolved, capability, store = await self._context(scope, generation, session)
            checked = await store.preflight(
                verify_capability(capability), mutation="write", path=path, fence=fence
            )
            await self._current(scope, resolved)
            result = await self.runtime.client.write(
                scope.user_id,
                resolved.binding,
                path=path,
                operation=operation,
                content=content,
                expected_digest=expected_digest,
                capability=capability,
                fence=checked["fence"],
            )
            await self._current(scope, resolved)
            return {"repository_id": str(scope.repository_id), "generation": generation, **result}
        except CollaborationConflict as error:
            raise _conflict(error) from None
        except CollaborationError:
            raise IdeEditError() from None
