"""Explicit coordinated repository writes, no legacy snapshots or shell endpoint."""

import base64
import binascii
import hashlib
from typing import Literal

from application.ide_writes import IdeWriteFailure
from fastapi import APIRouter, Header
from infrastructure.coordinator_client import CoordinationError, release_ide_lease
from infrastructure.ide_write_runtime import MAX_IMPORT_BYTES
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from presentation.routes.dependencies import WorkspaceRouteDependencies


class IdeWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    token: str
    path: str = Field(min_length=1, max_length=1024)
    operation: Literal["file", "directory"]
    content: str = Field(default="", max_length=262144)
    expected_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    coordination_capability: str = Field(min_length=1, max_length=2048)
    coordination_fence: int = Field(ge=1)


class IdeMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    token: str
    path: str = Field(min_length=1, max_length=1024)
    destination: str = Field(min_length=1, max_length=1024)
    expected_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    coordination_capability: str = Field(min_length=1, max_length=2048)
    coordination_fence: int = Field(ge=1)
    destination_fence: int = Field(ge=1)


class IdeAgentWriteRequest(IdeWriteRequest):
    # The coordinator acquires/checks the current agent lease inside the operation
    # lock. A model never supplies or sees the coordinator fence.
    coordination_fence: None = None


class IdeImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    token: str
    path: str = Field(min_length=1, max_length=1024)
    operation: Literal["import"]
    content: bytes = Field(repr=False, max_length=MAX_IMPORT_BYTES)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_digest: None = None
    coordination_capability: str = Field(min_length=1, max_length=2048)
    coordination_fence: int = Field(ge=1)

    @field_validator("content", mode="before")
    @classmethod
    def decode_content(cls, value):
        if type(value) is not str or len(value) > ((MAX_IMPORT_BYTES + 2) // 3) * 4:
            raise ValueError("invalid_import_bytes")
        try:
            return base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("invalid_import_bytes") from None

    @model_validator(mode="after")
    def check_digest(self):
        if hashlib.sha256(self.content).hexdigest() != self.sha256:
            raise ValueError("invalid_import_digest")
        return self


def create_ide_write_router(deps: WorkspaceRouteDependencies) -> APIRouter:
    router = APIRouter(tags=["ide-writes"])

    @router.post("/workspaces/{workspace_id}/ide/import")
    async def import_file(
        workspace_id: str,
        payload: IdeImportRequest,
        authorization: str | None = Header(default=None),
    ):
        return await perform_write(workspace_id, payload, authorization)

    @router.post("/workspaces/{workspace_id}/ide/agent/write")
    async def agent_write(
        workspace_id: str,
        payload: IdeAgentWriteRequest,
        authorization: str | None = Header(default=None),
    ):
        return await perform_write(workspace_id, payload, authorization)

    @router.post("/workspaces/{workspace_id}/ide/move")
    async def move(
        workspace_id: str, payload: IdeMoveRequest, authorization: str | None = Header(default=None)
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        registry = deps.registry()
        if registry is None:
            return deps.error("workspace_unavailable", "workspace is unavailable", 503)
        async with registry.operation(item):
            for path, fence in (
                (payload.path, payload.coordination_fence),
                (payload.destination, payload.destination_fence),
            ):
                guarded = await deps.coordination_guard(
                    payload.model_copy(update={"coordination_fence": fence}),
                    "write",
                    path=path,
                    workspace_id=workspace_id,
                )
                if deps.guard_denied(guarded):
                    return guarded
            try:
                return await registry.move_ide(
                    item,
                    path=payload.path,
                    destination=payload.destination,
                    expected_digest=payload.expected_digest,
                )
            except IdeWriteFailure as error:
                status = {
                    "ide_file_changed": 409,
                    "ide_file_missing": 404,
                    "ide_path_forbidden": 403,
                    "ide_file_unsupported": 422,
                    "ide_runtime_expired": 410,
                }.get(error.code, 503)
                return deps.error(error.code, "repository move is unconfirmed", status)

    @router.post("/workspaces/{workspace_id}/ide/write")
    async def write(
        workspace_id: str,
        payload: IdeWriteRequest,
        authorization: str | None = Header(default=None),
    ):
        return await perform_write(workspace_id, payload, authorization)

    async def perform_write(workspace_id, payload, authorization):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        registry = deps.registry()
        if registry is None:
            return deps.error("workspace_unavailable", "workspace is unavailable", 503)
        async with registry.operation(item):
            guarded = await deps.coordination_guard(
                payload, "write", path=payload.path, workspace_id=workspace_id
            )
            if deps.guard_denied(guarded):
                return guarded
            try:
                return await registry.write_ide(
                    item,
                    path=payload.path,
                    operation=payload.operation,
                    content=payload.content,
                    expected_digest=payload.expected_digest,
                )
            except IdeWriteFailure as error:
                status = {
                    "ide_path_forbidden": 403,
                    "ide_file_changed": 409,
                    "ide_file_missing": 404,
                    "ide_file_unsupported": 422,
                    "invalid_request": 422,
                    "ide_write_limit": 413,
                    "ide_runtime_expired": 410,
                }.get(error.code, 503)
                return deps.error(error.code, "repository write is unconfirmed", status)
            finally:
                if isinstance(payload, IdeAgentWriteRequest) and getattr(guarded, "fence", 0) > 0:
                    try:
                        await release_ide_lease(
                            payload.coordination_capability,
                            workspace_id=workspace_id,
                            path=payload.path,
                            fence=guarded.fence,
                        )
                    except CoordinationError:
                        # Exact actor/fence lease expires normally; never turn an
                        # acknowledged write into an ambiguous response on cleanup.
                        pass

    return router
