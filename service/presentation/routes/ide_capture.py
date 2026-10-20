"""Private verified capsule transport, not a public archive or Save endpoint."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from infrastructure.ide_bundle_format import CHUNK, BundleFailure, BundleLimits
from pydantic import BaseModel, ConfigDict, Field

from drivers.binary_exec import native_io, wait_owned
from presentation.routes.dependencies import WorkspaceRouteDependencies
from presentation.routes.ide_bundle_contracts import CaptureLimits


class IdeCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    user_id: str = Field(min_length=1, max_length=128)
    token: str = Field(min_length=1, max_length=2048, repr=False)
    expected_expires_at: int = Field(gt=0)
    coordination_capability: str = Field(min_length=1, max_length=2048, repr=False)
    limits: CaptureLimits


class _OwnedResponse(StreamingResponse):
    def __init__(self, body, resources: AsyncExitStack, **kwargs):
        super().__init__(body, **kwargs)
        self._resources = resources

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # BackgroundTask alone is insufficient: disconnect/send failures
            # must close the spool too, without racing borrowed native I/O.
            await wait_owned(asyncio.create_task(self._resources.aclose()))


def create_ide_capture_router(deps: WorkspaceRouteDependencies) -> APIRouter:
    router = APIRouter(tags=["ide-capture"])

    @router.post("/workspaces/{workspace_id}/ide/capture")
    async def capture(
        workspace_id: str,
        payload: IdeCaptureRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        registry = deps.registry()
        if registry is None:
            return deps.error("workspace_unavailable", "workspace is unavailable", 503)
        resources = AsyncExitStack()
        transferred = False
        try:
            # Waiting for another mutation is bounded too. No capture may
            # continue from an expired/deleted item borrowed before that wait.
            async with asyncio.timeout(35), registry.operation(item):
                for completed in (False, True):
                    current, failure = deps.owned(workspace_id, payload)
                    if failure is not None:
                        return failure
                    if current is not item or item.expires_at != payload.expected_expires_at:
                        return deps.error("workspace_conflict", "workspace generation changed", 409)
                    if item.policy.root != "/workspace" or item.expired():
                        return deps.error("workspace_not_found", "workspace is unavailable", 404)
                    guarded = await deps.coordination_guard(
                        payload, "capture", workspace_id=workspace_id
                    )
                    if deps.guard_denied(guarded):
                        return guarded
                    if not completed:
                        limits = BundleLimits(**payload.limits.model_dump())
                        if (
                            not limits.file_bytes <= limits.total_bytes <= item.policy.quota_bytes
                            or limits.archive_bytes > item.policy.quota_bytes
                        ):
                            raise BundleFailure("ide_bundle_limit")
                        capsule = await resources.enter_async_context(
                            registry.capture_ide(item, limits)
                        )

            # The helper and verification have finished. Transfer only immutable
            # owned bytes; a slow HTTP consumer must not keep the mutation lock.
            async def chunks():
                while body := await native_io(capsule.source.read, CHUNK):
                    yield body

            response = _OwnedResponse(
                chunks(),
                resources,
                media_type="application/octet-stream",
                headers={
                    "Content-Length": str(capsule.size),
                    "X-IDE-Capsule-SHA256": capsule.sha256,
                    "X-IDE-Capsule-Version": "1",
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )
            transferred = True
            return response
        except BundleFailure as error:
            # Failed capture is read-only and exposes no capsule, even when its
            # helper exit is uncertain. Never discard the user's runtime. This
            # does not apply to restore/materialization into a fresh allocation.
            status = (
                409
                if error.code in {"ide_bundle_busy", "ide_bundle_changed"}
                else 413
                if error.code == "ide_bundle_limit"
                else 503
            )
            return deps.error(error.code, "repository capture is unavailable", status)
        except TimeoutError:
            return deps.error("ide_bundle_unavailable", "repository capture timed out", 503)
        finally:
            if not transferred:
                await wait_owned(asyncio.create_task(resources.aclose()))

    return router
