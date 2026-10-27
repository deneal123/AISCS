"""Explicit durable provision; reads/replays can only observe a claimed generation."""

from __future__ import annotations

import time
from typing import Any

from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.domain.ide.files import IdeReadError
from service.services.chat.domain.ide.runtime import (
    RepositoryScope,
    ResolvedRuntime,
    RuntimeAttempt,
    RuntimeObservation,
)
from service.services.chat.persistence.ide.repositories import IdeRepositoryRepository
from service.services.chat.persistence.ide.runtime import IdeRuntimeRepository


class _ObservationAdvanced(Exception):
    """A private binding was superseded by another reader, not a new allocation."""


def public_runtime(scope: RepositoryScope, attempt: RuntimeAttempt | None) -> dict[str, Any]:
    return {
        "repository_id": str(scope.repository_id),
        "workspace": {
            "state": attempt.state if attempt else "not_created",
            "expires_at": attempt.expires_at if attempt else None,
            "can_retry": bool(attempt and attempt.state == "rejected" and attempt.retry_allowed),
        },
    }


class IdeRuntimeService:
    def __init__(
        self,
        repository: IdeRepositoryRepository,
        runtime: IdeRuntimeRepository,
        client: IdeWorkspaceClient,
        *,
        mutation_guard: Any = None,
    ) -> None:
        self.repository, self.runtime, self.client = repository, runtime, client
        self.mutation_guard = mutation_guard

    async def _check_owner(self, scope: RepositoryScope) -> None:
        if await self.repository.get_owned(**scope.params()) is None:
            raise IdeRepositoryNotFound

    async def status(self, scope: RepositoryScope) -> dict[str, Any]:
        await self._check_owner(scope)
        attempt = await self.runtime.get_owned(scope)
        if attempt is None:
            return public_runtime(scope, None)
        return await self._observe(scope, attempt, create=False)

    async def provision(
        self, scope: RepositoryScope, *, allow_retry: bool = True
    ) -> dict[str, Any]:
        await self._check_owner(scope)
        existing = await self.runtime.get_owned(scope)
        if existing is not None and (not allow_retry or not existing.retry_allowed):
            return await self._observe(scope, existing, create=False)
        ttl = await self.client.allocation_ttl()
        if ttl is None:
            result = public_runtime(scope, existing)
            result["workspace"].update(state="unavailable", can_retry=False)
            return result
        # The decorator's owned transaction commits before returning dispatch=True.
        # A lost commit ack cannot reach the create call below.
        claim_options = {} if allow_retry else {"allow_retry": False}
        attempt, dispatch = await self.runtime.claim(scope, ttl_sec=ttl, **claim_options)
        if attempt is None:
            raise IdeRepositoryNotFound
        return await self._observe(scope, attempt, create=dispatch)

    async def _observe(
        self, scope: RepositoryScope, attempt: RuntimeAttempt, *, create: bool
    ) -> dict[str, Any]:
        if attempt.state == "rejected" and not create and attempt.expires_at > time.time():
            return public_runtime(scope, attempt)
        current = await self.runtime.begin_observation(scope, attempt)
        if current is None:
            raise IdeRepositoryNotFound
        observation = (
            RuntimeObservation("expired")
            if current.expires_at <= time.time()
            else (await self.client.observe(scope.user_id, current, create=create))
        )
        recorded = await self.runtime.record_observation(
            scope, current, observation.state, retry_allowed=observation.retry_allowed
        )
        if recorded is None:
            raise IdeRepositoryNotFound
        return public_runtime(scope, recorded)

    async def resolve(self, scope: RepositoryScope) -> ResolvedRuntime:
        """Resolve credentials privately. Reads must never provision or rearm."""
        try:
            return await self._resolve_once(scope)
        except _ObservationAdvanced:
            # Discard the first binding completely. Obtain a NEW, fenced reply
            # once; never reuse superseded credentials or retry any mutation.
            try:
                return await self._resolve_once(scope)
            except _ObservationAdvanced:
                raise IdeReadError("ide_generation_changed") from None

    async def _resolve_once(self, scope: RepositoryScope) -> ResolvedRuntime:
        await self._check_owner(scope)
        attempt = await self.runtime.get_owned(scope)
        if attempt is None or attempt.state == "rejected":
            raise IdeReadError("ide_runtime_not_ready")
        current = await self.runtime.begin_observation(scope, attempt)
        if current is None:
            raise IdeRepositoryNotFound
        observation = (
            RuntimeObservation("expired")
            if current.expires_at <= time.time()
            else (await self.client.observe(scope.user_id, current, create=False))
        )
        recorded = await self.runtime.record_observation(
            scope, current, observation.state, retry_allowed=False
        )
        if recorded is None:
            raise IdeRepositoryNotFound
        if recorded.allocation_id != current.allocation_id:
            raise IdeReadError("ide_generation_changed")
        if recorded.observation != current.observation:
            if (
                recorded.state == "ready"
                and recorded.expires_at > time.time()
                and observation.state == "ready"
                and observation.binding is not None
            ):
                raise _ObservationAdvanced
            raise IdeReadError("ide_generation_changed")
        if observation.state == "expired":
            raise IdeReadError("ide_runtime_expired")
        if observation.state != "ready" or observation.binding is None:
            raise IdeReadError("ide_runtime_not_ready")
        return ResolvedRuntime(recorded, observation.binding)
