"""Read a frozen owned generation, never the thread's legacy/PDF workspace."""

from __future__ import annotations

import time
from typing import Any

from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.ide.files import IdeReadError, validate_path
from service.services.chat.domain.ide.runtime import RepositoryScope, generation_tag


class IdeReadService:
    def __init__(self, runtime: IdeRuntimeService) -> None:
        self.runtime = runtime

    async def read(
        self, scope: RepositoryScope, *, operation: str, path: str, generation: str | None = None
    ) -> dict[str, Any]:
        if operation not in {"tree", "file"}:
            raise IdeReadError()
        path = validate_path(path, root_allowed=operation == "tree")
        resolved = await self.runtime.resolve(scope)
        tag = generation_tag(resolved.attempt)
        if generation is not None and generation != tag:
            raise IdeReadError("ide_generation_changed")
        data = await self.runtime.client.read(
            scope.user_id, resolved.binding, operation=operation, path=path
        )
        # A reset/deletion/expiry during the RPC cannot publish retired contents.
        current = await self.runtime.runtime.get_owned(scope)
        if current is None:
            raise IdeRepositoryNotFound
        if current.allocation_id != resolved.attempt.allocation_id:
            raise IdeReadError("ide_generation_changed")
        if current.expires_at <= time.time():
            raise IdeReadError("ide_runtime_expired")
        if current.state != "ready":
            raise IdeReadError("ide_runtime_not_ready")
        return {"repository_id": str(scope.repository_id), "generation": tag, **data}
