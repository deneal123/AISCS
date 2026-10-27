"""Prepare the first PDF project, never rebuild an expired/uncertain environment.

The descriptor transaction ends before dispatch. A second tab or lost response
can only look up the persisted allocation and inspect the same project path.
The existing private allocation client is reused without creating an IDE repo.
"""

import math
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress

from service.infrastructure import workspace_client
from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.infrastructure.pdf_workspace_binding import current_pdf_binding, publish_pdf_binding
from service.services.chat.application.workspace_collaboration import (
    CollaborationError,
    WorkspaceCollaborationStore,
    mint_capability,
    verify_capability,
)
from service.services.chat.domain.documents.preparation import (
    PdfPreparation,
    PdfPreparationNotFound,
    PdfPreparationScope,
    PdfPreparationUnavailable,
)
from service.services.chat.domain.ide.runtime import RuntimeAttempt
from service.services.chat.domain.workspace_view import project_workspace_view
from service.services.chat.persistence.documents.preparation import PdfPreparationRepository

DEFAULT_PDF_PATH = "documents/default"


def _project_path(view: dict) -> str | None:
    if any(item.get("path") == "document.toml" for item in view["entries"]):
        # Legacy root projects need explicit selection, never a second scaffold.
        raise PdfPreparationUnavailable
    paths = sorted(
        str(item.get("path") or "").removesuffix("/document.toml")
        for item in view["entries"]
        if item.get("type") == "file" and str(item.get("path") or "").endswith("/document.toml")
    )
    return paths[0] if paths else None


class PdfPreparationService:
    def __init__(
        self,
        repository: PdfPreparationRepository,
        allocator: IdeWorkspaceClient,
        redis,
        initialize: Callable[[dict, dict, int], Awaitable[bool]] | None = None,
    ) -> None:
        self.repository, self.allocator, self.redis = repository, allocator, redis
        self.initialize = initialize

    async def prepare(self, scope: PdfPreparationScope, *, retry_scaffold: bool = False) -> dict:
        if not await self.repository.ensure_owner(scope):
            raise PdfPreparationNotFound
        state, existing = await workspace_client.read_binding_state(
            self.redis, str(scope.thread_id)
        )
        if state == "unavailable":
            raise PdfPreparationUnavailable
        intent = await self.repository.get_owned(scope)
        dispatch = False
        if intent is None:
            intent, dispatch = await self._claim(scope, existing)
        if intent.expires_at <= time.time():
            return {"state": "expired"}
        ref = await self._resolve(scope, intent, existing, dispatch=dispatch)
        if ref is None:
            return {"state": "expired" if intent.expires_at <= time.time() else "unavailable"}
        await current_pdf_binding(self.redis, ref)
        try:
            path, view = await self._project(scope, intent, ref, retry_scaffold=retry_scaffold)
        except workspace_client.WorkspaceGone:
            return {"state": "expired"}
        except (workspace_client.WorkspaceUnavailable, CollaborationError):
            raise PdfPreparationUnavailable from None
        await current_pdf_binding(self.redis, ref)
        if not await self.repository.observe_project(scope):
            raise PdfPreparationUnavailable
        return {"state": "ready", "project_path": path, "workspace": view}

    async def _claim(self, scope: PdfPreparationScope, existing: dict | None):
        if existing:
            workspace_id = str(existing.get("workspace_id") or "")
            try:
                expiry = float(existing.get("expires_at") or 0)
            except (TypeError, ValueError):
                raise PdfPreparationUnavailable from None
            if (
                not re.fullmatch(r"[a-f0-9]{32}", workspace_id)
                or not math.isfinite(expiry)
                or expiry <= 0
            ):
                raise PdfPreparationUnavailable
            intent, dispatch = await self.repository.claim(
                scope, ttl_sec=1, workspace_id=workspace_id, expires_at=int(expiry)
            )
        else:
            ttl = await self.allocator.allocation_ttl()
            if ttl is None:
                raise PdfPreparationUnavailable
            intent, dispatch = await self.repository.claim(scope, ttl_sec=ttl)
        if intent is None:
            raise PdfPreparationNotFound
        return intent, dispatch

    async def _resolve(
        self,
        scope: PdfPreparationScope,
        intent: PdfPreparation,
        existing: dict | None,
        *,
        dispatch: bool,
    ) -> dict | None:
        owner = {"thread_id": str(scope.thread_id), "user_id": str(scope.user_id)}
        if intent.allocation_id is None:
            if existing and existing.get("workspace_id") == intent.workspace_id:
                return {**existing, **owner}
            return None
        attempt = RuntimeAttempt(intent.allocation_id, intent.expires_at, "dispatching", 0)
        observation = await self.allocator.observe(
            scope.user_id, attempt, create=dispatch, initialize_history=dispatch
        )
        binding = observation.binding
        if observation.state != "ready" or binding is None:
            return None
        return await publish_pdf_binding(
            self.redis,
            {
                **owner,
                "workspace_id": binding.workspace_id,
                "token": binding.token,
                "root": binding.root,
                "expires_at": binding.expires_at,
            },
        )

    async def _read(self, ref: dict) -> dict:
        raw = await workspace_client.view(ref)
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("entries"), list)
            or not isinstance(raw.get("revision"), str)
            or not raw["revision"]
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not item["path"]
                for item in raw["entries"]
            )
        ):
            raise PdfPreparationUnavailable
        return project_workspace_view(ref, raw)

    async def _project(
        self, scope: PdfPreparationScope, intent: PdfPreparation, ref: dict, *, retry_scaffold: bool
    ) -> tuple[str, dict]:
        view = await self._read(ref)
        path = _project_path(view)
        if path:
            return path, view
        # Incomplete discovery is not proof that this is a new, empty project.
        if (
            view["truncated"]
            or intent.scaffold_state in {"observed", "dispatching"}
            or (intent.scaffold_state == "rejected" and not retry_scaffold)
        ):
            raise PdfPreparationUnavailable
        token = mint_capability(
            ref["workspace_id"],
            role="ui",
            actor_seed=f"pdf-entry:{secrets.token_hex(16)}",
            expires_at=ref["expires_at"],
        )
        capability = verify_capability(token)
        store = WorkspaceCollaborationStore(
            self.redis,
            workspace_id=ref["workspace_id"],
            expires_at=ref["expires_at"],
            thread_id=ref["thread_id"],
        )
        lease = await store.acquire_lease(capability, DEFAULT_PDF_PATH)
        try:
            scoped = {**ref, "coordination_capability": token}
            admitted = await self.repository.claim_scaffold(scope, allow_retry=retry_scaffold)
            created = await self._scaffold(scope, scoped, view, lease.fence) if admitted else None
            if created and self.initialize:
                await self.initialize(scoped, created, lease.fence)
        finally:
            with suppress(CollaborationError):
                await store.release_lease(capability, DEFAULT_PDF_PATH, lease.fence)
        # An acknowledgement alone does not mean the project is discoverable.
        view = await self._read(ref)
        path = _project_path(view)
        if not path:
            raise PdfPreparationUnavailable
        return path, view

    async def _scaffold(
        self, scope: PdfPreparationScope, ref: dict, view: dict, fence: int
    ) -> dict | None:
        try:
            result = await workspace_client.create_document_project(
                ref,
                path=DEFAULT_PDF_PATH,
                profile_id="generic_document",
                mode="draft",
                locale="ru-RU",
                expected_revision=view["revision"],
                fence=fence,
            )
            if (
                isinstance(result, dict)
                and result.get("path") == DEFAULT_PDF_PATH
                and result.get("revision_changed") is True
                and isinstance(result.get("revision"), str)
                and result["revision"]
            ):
                return result
        except workspace_client.WorkspaceConflict:
            # Only a confirmed rejection can be rearmed by a new user action.
            await self.repository.reject_scaffold(scope)
        except workspace_client.WorkspaceUnavailable:
            # The next operation is a read, never another scaffold/alternate path.
            pass
        return None
