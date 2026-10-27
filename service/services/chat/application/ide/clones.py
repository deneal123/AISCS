"""An explicit isolated clone, with durable dispatch and no blind Git replay."""

import asyncio
import hashlib
import json
import time
from typing import Any
from uuid import UUID

from service.infrastructure.ide.transports.git_fetch import branch_name, parse_origin
from service.services.chat.application.ide.edits import IdeEditService, validate_ide_session
from service.services.chat.application.ide.repositories import (
    IdeRepositoryIntentConflict,
    IdeRepositoryNotFound,
    public_repository,
)
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.ide.edits import EDIT_ERRORS, IdeEditError
from service.services.chat.domain.ide.files import IdeReadError
from service.services.chat.domain.ide.runtime import RepositoryScope, generation_tag
from service.services.chat.persistence.ide.clones import IdeCloneRepository


def public_clone(row: dict[str, Any]) -> dict[str, Any]:
    state = row["state"]
    if state == "cloning" and time.time() - row["started_at"] > 90:
        state = "unconfirmed"
    return {
        "repository": public_repository(row),
        "state": {"reserved": "preparing", "cloning": "running"}.get(state, state),
        "code": row["code"] if row["code"] in EDIT_ERRORS else None,
    }


def clone_digest(source_id: UUID, origin: str, branch: str) -> str:
    return hashlib.sha256(
        json.dumps([str(source_id), origin, branch], separators=(",", ":")).encode()
    ).hexdigest()


def recovery_clone(row: dict[str, Any]) -> dict[str, Any]:
    request = None
    origin, branch = row.get("origin"), row.get("branch")
    try:
        if (
            isinstance(origin, str)
            and isinstance(branch, str)
            and (not branch or branch_name(branch))
        ):
            canonical = parse_origin(origin)
            if canonical == origin and row["request_digest"] == clone_digest(
                row["source_repository_id"], canonical, branch
            ):
                request = {"origin": canonical, "branch": branch}
    except IdeEditError:
        pass  # Legacy/corrupt parameters are inspection-only, never a guessed replay.
    return {
        **public_clone(row),
        "intent_id": str(row["intent_id"]),
        "source_repository_id": str(row["source_repository_id"]),
        "request": request,
    }


class IdeCloneService:
    def __init__(self, runtime: IdeRuntimeService, journal: IdeCloneRepository, redis: Any):
        self.runtime, self.journal, self.redis = runtime, journal, redis

    async def status(self, *, thread_id: UUID, user_id: UUID, intent_id: UUID) -> dict[str, Any]:
        row = await self.journal.get_owned(
            thread_id=thread_id, user_id=user_id, intent_id=intent_id
        )
        if row is None:
            raise IdeRepositoryNotFound
        return public_clone(row)

    async def recover(self, scope: RepositoryScope) -> dict[str, Any]:
        if await self.runtime.repository.get_owned(**scope.params()) is None:
            raise IdeRepositoryNotFound
        row = await self.journal.latest_owned(scope)
        return {"attempt": recovery_clone(row) if row else None}

    async def clone(
        self,
        source: RepositoryScope,
        *,
        intent_id: UUID,
        origin: str,
        branch: str,
        session: str | None,
    ) -> dict[str, Any]:
        session = validate_ide_session(session)
        origin = parse_origin(origin)
        if branch and not branch_name(branch):
            raise IdeEditError("ide_git_branch_missing")
        digest = clone_digest(source.repository_id, origin, branch)
        row = await self.journal.reserve(
            source,
            intent_id=intent_id,
            request_digest=digest,
            name=origin.rsplit("/", 1)[-1].removesuffix(".git")[:120],
            origin=origin,
            branch=branch,
        )
        if row is None:
            raise IdeRepositoryNotFound
        if row.get("conflict") or row["request_digest"] != digest:
            raise IdeRepositoryIntentConflict
        lookup = {"thread_id": source.thread_id, "user_id": source.user_id, "intent_id": intent_id}
        if row["state"] != "reserved":
            return public_clone(row)
        destination = RepositoryScope(source.thread_id, source.user_id, row["repository_id"])
        # Only reads after the one durable allocation claim. Slow starts remain
        # observable under the same intent; they never create another project.
        try:
            async with asyncio.timeout(20):
                runtime = await self.runtime.provision(destination, allow_retry=False)
                for _ in range(20):
                    if runtime["workspace"]["state"] not in {"pending", "dispatching"}:
                        break
                    await asyncio.sleep(0.5)
                    runtime = await self.runtime.status(destination)
        except TimeoutError:
            return public_clone(row)
        if runtime["workspace"]["state"] != "ready":
            return {
                **public_clone(row),
                "state": "preparing"
                if runtime["workspace"]["state"] in {"pending", "dispatching"}
                else "blocked",
            }
        if not await self.journal.claim(**lookup):
            return await self.status(**lookup)
        try:
            async with asyncio.timeout(65):
                attempt = await self.runtime.runtime.get_owned(destination)
                if attempt is None:
                    raise IdeEditError("ide_runtime_not_ready")
                result = await IdeEditService(self.runtime, self.redis).git(
                    destination,
                    generation=generation_tag(attempt),
                    session=session,
                    operation="clone",
                    origin=origin,
                    branch=branch,
                    clone_intent_id=intent_id,
                )
                if result.get("initialized") is not True:
                    raise IdeEditError("ide_git_unconfirmed")
        except (IdeEditError, IdeReadError, TimeoutError) as error:
            code = getattr(error, "code", "ide_git_unconfirmed")
            definitive = code in {
                "ide_git_not_empty",
                "ide_git_conflict",
                "ide_git_url_invalid",
                "ide_git_branch_missing",
                "ide_git_limit",
                "ide_git_fetch_failed",
                "ide_git_invalid",
            }
            await self.journal.finish(
                **lookup, state="failed" if definitive else "unconfirmed", code=code
            )
        else:
            await self.journal.finish(**lookup, state="complete", code=None)
        return await self.status(**lookup)
