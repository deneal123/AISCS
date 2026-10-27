"""First-entry orchestration; no automatic quota retry or replacement of expired work."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from service.services.chat.application.ide.edits import IdeEditService, validate_ide_session
from service.services.chat.application.ide.repositories import IdeRepositoryService
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.ide.edits import IdeEditError
from service.services.chat.domain.ide.files import IdeReadError
from service.services.chat.domain.ide.runtime import RepositoryScope, generation_tag


class IdePrepareService:
    def __init__(self, runtime: IdeRuntimeService, redis: Any):
        self.runtime, self.redis = runtime, redis

    async def prepare(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        session: str | None,
        repository_id: UUID | None = None,
    ) -> dict[str, Any]:
        # Invalid admission cannot even create a descriptor or a draft chat.
        session = validate_ide_session(session)
        repositories = IdeRepositoryService(self.runtime.repository)
        descriptor = (
            await repositories.ensure_default(thread_id=thread_id, user_id=user_id)
            if repository_id is None
            else await repositories.get(
                thread_id=thread_id, user_id=user_id, repository_id=repository_id
            )
        )
        scope = RepositoryScope(thread_id, user_id, UUID(descriptor["repository_id"]))
        state = await self.runtime.provision(scope, allow_retry=False)
        result = {"repository": descriptor, "runtime": state, "git": None}
        if state["workspace"]["state"] != "ready":
            return result
        # Inspecting a reserved/interrupted clone must not create .git in its
        # destination before the clone has published. Existing Git is read later.
        if await self.runtime.repository.is_clone_destination(**scope.params()):
            return result
        # The IDE entry contract includes Git initialization. The trusted init
        # operation returns status without changing an existing .git, and never
        # stages or alters user files in a repository that has no Git yet.
        # Starter provenance remains a separate, stricter clone replacement gate.
        attempt = await self.runtime.runtime.get_owned(scope)
        if attempt is None:
            result["git_error"] = "ide_runtime_not_ready"
            return result
        try:
            git = await IdeEditService(self.runtime, self.redis).git(
                scope, generation=generation_tag(attempt), session=session, operation="init"
            )
            result["git"] = {key: git[key] for key in ("initialized", "branch")}
        except (IdeEditError, IdeReadError) as error:
            # Keep the confirmed project/runtime outcome. Recovery re-observes
            # that same generation, never creates a second environment.
            result["git_error"] = error.code
        return result
