"""File and history HTTP routes for a thread workspace.

The module owns endpoint orchestration.  ``workspace_api`` remains the public
compatibility facade; resolving it lazily also preserves the narrow monkeypatch
seams used by older in-process callers.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from service.composition.state import get_chat_application_service, get_optional_redis_client
from service.models.auth_models import AuthProfile
from service.services.chat.application.chat_application_service import ChatApplicationService
from service.services.chat.presentation.routers.chat_api.workspace_contracts import (
    DiffRequest,
    PathRequest,
    RevertRequest,
)
from service.services.chat.presentation.routers.chat_api.workspace_metrics import (
    WorkspaceMetricsRoute,
)
from service.shared.security.auth_checker import check_auth

router = APIRouter(route_class=WorkspaceMetricsRoute)
WorkspaceSessionHeader = Annotated[str | None, Header(alias="X-Workspace-Session")]


def _runtime():
    from service.services.chat.presentation.routers.chat_api import workspace_api

    return workspace_api


@router.get("/{thread_id}/workspace")
async def workspace_tree(
    thread_id: str,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    path: str = "",
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    async with runtime._alive(redis, thread_id):
        tree = await runtime.workspace_client.tree(ref, path)
    if isinstance(tree, list):
        tree = {"entries": tree}
    root = str(ref.get("root") or "/workspace")
    return {
        "root": root,
        "entries": [
            {**item, "path": str(item.get("path") or "").removeprefix(root).lstrip("/")}
            for item in tree.get("entries", [])
        ],
        "revision": str(tree.get("revision") or ""),
        "recovered": bool(tree.get("recovered")),
    }


@router.post("/{thread_id}/workspace/file")
async def workspace_file(
    thread_id: str,
    payload: Annotated[PathRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    async with runtime._alive(redis, thread_id):
        data = await runtime.workspace_client.read_file(ref, payload.path)
    if data is None:
        raise HTTPException(status_code=404, detail="Файла нет или прочитать не удалось")
    return data


@router.get("/{thread_id}/workspace/history")
async def workspace_history(
    thread_id: str,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    async with runtime._alive(redis, thread_id):
        history = await runtime.workspace_client.history(ref)
    return history if isinstance(history, dict) else {"entries": history}


@router.post("/{thread_id}/workspace/diff")
async def workspace_diff(
    thread_id: str,
    payload: Annotated[DiffRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    async with runtime._alive(redis, thread_id):
        return {"diff": await runtime.workspace_client.diff(ref, payload.ref, payload.path)}


@router.post("/{thread_id}/workspace/revert")
async def workspace_revert(
    thread_id: str,
    payload: Annotated[RevertRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    workspace_session: WorkspaceSessionHeader = None,
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    ref = {
        **ref,
        "coordination_capability": runtime._request_ui_capability(
            ref, str(profile.user_id), workspace_session
        ),
    }
    try:
        async with runtime._alive(redis, thread_id):
            result = await runtime.workspace_client.revert(
                ref, payload.ref, payload.expected_revision, payload.path
            )
    except runtime.workspace_client.WorkspaceConflict as exc:
        raise HTTPException(
            status_code=409, detail="Рабочее место изменилось; обновите дерево"
        ) from exc
    if not (result or {}).get("reverted"):
        raise HTTPException(status_code=409, detail="Откат не выполнен: нет истории или ревизии")
    return {
        "reverted": True,
        "ref": payload.ref,
        "path": payload.path,
        "revision": result.get("revision"),
    }
