"""Private capsule upload into a fresh allocation, never an existing repository.

The trusted backend must durably claim dispatch before invoking this transport.
This endpoint does not choose a saved revision or implement user retention.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from tempfile import SpooledTemporaryFile
from typing import Annotated

from application.allocations import (
    AllocationConflict,
    AllocationExpired,
    AllocationPending,
    WorkspaceAllocation,
)
from application.lifecycle import TooManyWorkspaces
from application.recovery import RestoreSnapshot as SnapshotIdentity
from domain.policy import WorkspacePolicy
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from infrastructure.ide_bundle_format import CHUNK, BundleFailure, BundleLimits
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import ClientDisconnect

from drivers import DriverError, IsolationUnverified
from drivers.binary_exec import native_io
from presentation.routes.contracts import AllocationRequest
from presentation.routes.dependencies import WorkspaceRouteDependencies
from presentation.routes.ide_bundle_contracts import CaptureLimits


class RestoreSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    size: int = Field(gt=0, lt=2**31)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$", min_length=64, max_length=64, repr=False)


class IdeRestoreLookup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    user_id: str = Field(min_length=1, max_length=128)
    allocation: AllocationRequest
    snapshot: RestoreSnapshot


class IdeRestoreRequest(IdeRestoreLookup):
    limits: CaptureLimits


def _restored_reply(item, token: str, expected: RestoreSnapshot, expires_at: int) -> JSONResponse:
    restored = SnapshotIdentity(expected.sha256, expected.size)
    if (
        item.restore_snapshot != restored
        or type(item.expires_at) not in (int, float)
        or item.expires_at != expires_at
    ):
        raise AllocationConflict
    return JSONResponse(
        {
            "workspace_id": item.workspace_id,
            "token": token,
            "root": item.policy.root,
            "expires_at": expires_at,
            "policy": item.policy.as_dict(),
            "restore_snapshot": {"sha256": restored.sha256, "size": restored.size},
        },
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def create_ide_restore_router(deps: WorkspaceRouteDependencies) -> APIRouter:
    router = APIRouter(tags=["ide-restore"])

    @router.post("/workspaces/allocations/restore/lookup")
    async def lookup(
        authorization: str | None = Header(default=None),
        metadata: Annotated[list[str] | None, Header(alias="X-IDE-Restore-Request")] = None,
    ):
        deps.auth(authorization)
        registry = deps.registry()
        if registry is None:
            return deps.error("workspace_unavailable", "workspace is unavailable", 503)
        if not metadata or len(metadata) != 1 or len(metadata[0].encode("utf-8")) > 4096:
            return deps.error("invalid_request", "restore metadata is invalid", 422)
        try:
            payload = IdeRestoreLookup.model_validate_json(metadata[0])
            allocation = WorkspaceAllocation(**payload.allocation.model_dump())
            allocation.remaining()
            # No inventory scan, capsule read, provision, Git or expiry refresh.
            item = registry.lookup_allocation(payload.user_id, allocation)
            if item is None:
                return deps.error("workspace_not_found", "allocation was not found", 404)
            return _restored_reply(
                item,
                registry.allocation_token(item, payload.user_id),
                payload.snapshot,
                allocation.expires_at,
            )
        except AllocationPending:
            return deps.error("workspace_allocation_pending", "allocation is pending", 409)
        except AllocationConflict:
            return deps.error("workspace_allocation_conflict", "allocation changed", 409)
        except AllocationExpired:
            return deps.error("workspace_allocation_expired", "allocation expired", 410)
        except (ValidationError, TypeError, ValueError):
            return deps.error("invalid_request", "restore metadata is invalid", 422)

    @router.post("/workspaces/allocations/restore")
    async def restore(
        request: Request,
        authorization: str | None = Header(default=None),
        metadata: Annotated[list[str] | None, Header(alias="X-IDE-Restore-Request")] = None,
    ):
        deps.auth(authorization)
        registry = deps.registry()
        if registry is None:
            return deps.error("workspace_unavailable", "workspace is unavailable", 503)
        if not metadata or len(metadata) != 1 or len(metadata[0].encode("utf-8")) > 4096:
            return deps.error("invalid_request", "restore metadata is invalid", 422)
        try:
            payload = IdeRestoreRequest.model_validate_json(metadata[0])
            allocation = WorkspaceAllocation(**payload.allocation.model_dump())
            allocation.remaining()
            policy = WorkspacePolicy()
            limits = BundleLimits(**payload.limits.model_dump())
            if (
                not limits.file_bytes <= limits.total_bytes <= policy.quota_bytes
                or limits.archive_bytes > policy.quota_bytes
                or payload.snapshot.size > limits.archive_bytes
            ):
                raise BundleFailure("ide_bundle_limit")
            if (
                request.headers.getlist("content-type") != ["application/octet-stream"]
                or request.headers.getlist("content-length") != [str(payload.snapshot.size)]
                or request.headers.get("content-encoding") is not None
                or request.headers.get("transfer-encoding") is not None
            ):
                return deps.error("invalid_request", "restore body framing is invalid", 422)
            # No runtime is allocated until every declared byte and digest has
            # arrived. Native verification still validates the capsule format.
            with SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as source:
                async with asyncio.timeout(40):
                    size, digest = 0, hashlib.sha256()
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > payload.snapshot.size:
                            raise BundleFailure()
                        digest.update(chunk)
                        for offset in range(0, len(chunk), CHUNK):
                            part = chunk[offset : offset + CHUNK]
                            if await native_io(source.write, part) != len(part):
                                raise BundleFailure()
                    if size != payload.snapshot.size or not hmac.compare_digest(
                        digest.hexdigest(), payload.snapshot.sha256
                    ):
                        raise BundleFailure()
                    allocation.remaining()
                    await native_io(source.seek, 0)
                    item, token = await registry.create_restored(
                        payload.user_id,
                        policy,
                        allocation=allocation,
                        source=source,
                        limits=limits,
                        expected_size=size,
                        expected_sha256=payload.snapshot.sha256,
                    )
            return _restored_reply(item, token, payload.snapshot, allocation.expires_at)
        except AllocationPending:
            return deps.error("workspace_allocation_pending", "allocation is pending", 409)
        except AllocationConflict:
            return deps.error("workspace_allocation_conflict", "allocation changed", 409)
        except AllocationExpired:
            return deps.error("workspace_allocation_expired", "allocation expired", 410)
        except (ValidationError, TypeError, ValueError):
            return deps.error("invalid_request", "restore metadata is invalid", 422)
        except BundleFailure as error:
            status = 413 if error.code == "ide_bundle_limit" else 503
            return deps.error(error.code, "repository restoration is unavailable", status)
        except TooManyWorkspaces:
            return deps.error("quota_exceeded", "workspace capacity is exhausted", 413)
        except IsolationUnverified:
            return deps.error("isolation_unverified", "workspace isolation was not verified", 500)
        except DriverError:
            return deps.error("driver_failed", "workspace driver failed", 502)
        except (TimeoutError, ClientDisconnect, OSError):
            return deps.error(
                "ide_bundle_unavailable", "repository restoration is unavailable", 503
            )

    return router
