"""Explicit Git setup. Public URLs are fetched by the backend, never this sandbox."""

import base64
from typing import Literal

from application.ide_git import IdeGitFailure
from fastapi import APIRouter, Header
from pydantic import BaseModel, ConfigDict, Field


class IdeGitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    token: str
    operation: Literal["status", "init", "clone"]
    branch: str = Field(default="main", max_length=200)
    origin: str = Field(default="", max_length=512)
    commit: str = Field(default="", max_length=40)
    pack: str = Field(default="", max_length=28 * 1024 * 1024)
    replace_pristine_starter: bool = Field(default=False, strict=True)
    coordination_capability: str = Field(min_length=1, max_length=2048)


def create_ide_git_router(deps):
    router = APIRouter(tags=["ide-git"])

    @router.post("/workspaces/{workspace_id}/ide/git")
    async def operation(
        workspace_id: str, payload: IdeGitRequest, authorization: str | None = Header(default=None)
    ):
        deps.auth(authorization)
        item, failure = deps.owned(workspace_id, payload)
        if failure is not None:
            return failure
        registry = deps.registry()
        if registry is None:
            return deps.error("workspace_unavailable", "workspace is unavailable", 503)
        async with registry.operation(item):
            guarded = await deps.coordination_guard(payload, "snapshot", workspace_id=workspace_id)
            if deps.guard_denied(guarded):
                return guarded
            try:
                pack = base64.b64decode(payload.pack, validate=True)
                if len(pack) > 20 * 1024 * 1024:
                    raise IdeGitFailure("ide_git_limit")
                return await registry.git_ide(
                    item,
                    operation=payload.operation,
                    branch=payload.branch,
                    origin=payload.origin,
                    commit=payload.commit,
                    pack=pack,
                    replace_pristine_starter=payload.replace_pristine_starter,
                )
            except (ValueError, IdeGitFailure) as error:
                code = error.code if isinstance(error, IdeGitFailure) else "ide_git_invalid"
                status = (
                    409
                    if code in {"ide_git_conflict", "ide_git_not_empty"}
                    else 413
                    if code == "ide_git_limit"
                    else 503
                )
                return deps.error(code, "repository operation is unconfirmed", status)

    return router
