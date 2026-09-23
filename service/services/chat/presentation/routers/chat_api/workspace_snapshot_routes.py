"""Independent Work Hub snapshot, activation, and library routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from service.composition.state import (
    get_chat_application_service,
    get_file_saver_service,
    get_optional_redis_client,
)
from service.models.auth_models import AuthProfile
from service.services.chat.application.chat_application_service import ChatApplicationService
from service.services.chat.presentation.routers.chat_api.work_snapshot import (
    WORK_SNAPSHOT_VERSION,
    empty_work_snapshot,
    library_snapshot,
    project_workspace_view,
    room_state,
    unavailable_library,
    workspace_state,
)
from service.services.chat.presentation.routers.chat_api.workspace_metrics import (
    WorkspaceMetricsRoute,
)
from service.services.files.application.file_saver_service import FileSaverService
from service.shared.security.auth_checker import check_auth

router = APIRouter(route_class=WorkspaceMetricsRoute)


def _runtime():
    from service.services.chat.presentation.routers.chat_api import workspace_api

    return workspace_api


@router.get("/{thread_id}/workspace/room")
async def workspace_room(
    thread_id: str,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    try:
        store = runtime._collaboration(ref, redis)
        tree = await runtime.workspace_client.tree(ref)
        return await store.snapshot(revision=str((tree or {}).get("revision") or ""))
    except runtime.CollaborationError as exc:
        raise runtime._collaboration_http_error(exc) from exc


async def ready_work_snapshot(ref: dict, *, thread_id: str, redis, library: dict) -> dict:
    """Read independent facets; a single dependency outage never blanks Work."""
    runtime = _runtime()
    workspace_gone = False
    try:
        async with runtime._alive(redis, thread_id):
            view = await runtime.workspace_client.view(ref)
        workspace = project_workspace_view(ref, view)
    except runtime.workspace_client.WorkspaceGone:
        await runtime.workspace_client.forget_binding(redis, thread_id)
        workspace = workspace_state("expired")
        view = {}
        workspace_gone = True
    except HTTPException as exc:
        state = "expired" if exc.status_code == 410 else "unavailable"
        workspace = workspace_state(state)
        view = {}
        workspace_gone = exc.status_code == 410
    except Exception:
        runtime.logger.warning(
            "work snapshot facet unavailable",
            extra={"component": "workspace", "failure_code": "unavailable"},
        )
        workspace = workspace_state("unavailable")
        view = {}

    if workspace_gone:
        room = room_state("expired")
    else:
        try:
            raw_room = await runtime._collaboration(ref, redis).snapshot(
                revision=str(view.get("revision") or "")
            )
            issues = list(raw_room.pop("issues", []) or [])
            room = {**raw_room, "state": "ready", "issues": [], "issue_count": len(issues)}
        except (runtime.CollaborationError, HTTPException):
            room = room_state("unavailable")
        except Exception:
            runtime.logger.warning(
                "work snapshot facet unavailable",
                extra={"component": "room", "failure_code": "unavailable"},
            )
            room = room_state("unavailable")
    return {
        "contract_version": WORK_SNAPSHOT_VERSION,
        "workspace": workspace,
        "room": room,
        "library": library,
    }


@router.get("/{thread_id}/work")
async def work_snapshot(
    thread_id: str,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    file_service: FileSaverService = Depends(get_file_saver_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    cursor: Annotated[str, Query(max_length=256)] = "",
):
    runtime = _runtime()
    await service.ensure_thread_owner(thread_id, str(profile.user_id))
    try:
        library = await library_snapshot(file_service, profile.user_id, limit=limit, cursor=cursor)
    except HTTPException:
        raise
    except Exception:
        runtime.logger.warning(
            "work snapshot facet unavailable",
            extra={"component": "library", "failure_code": "unavailable"},
        )
        library = unavailable_library()
    binding_state, ref = await runtime.workspace_client.read_binding_state(redis, thread_id)
    if binding_state == "unavailable":
        return {
            "contract_version": WORK_SNAPSHOT_VERSION,
            "workspace": workspace_state("unavailable"),
            "room": room_state("unavailable"),
            "library": library,
        }
    if not ref:
        return empty_work_snapshot(library)
    return await ready_work_snapshot(
        {**ref, "user_id": str(profile.user_id)},
        thread_id=thread_id,
        redis=redis,
        library=library,
    )


@router.post("/{thread_id}/work/activate")
async def activate_work(
    thread_id: str,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    file_service: FileSaverService = Depends(get_file_saver_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    cursor: Annotated[str, Query(max_length=256)] = "",
):
    runtime = _runtime()
    await service.ensure_thread_owner(thread_id, str(profile.user_id))
    ref = await runtime.workspace_client.ensure_workspace_explicit(
        redis, thread_id, str(profile.user_id)
    )
    if not ref:
        raise HTTPException(status_code=503, detail="Не удалось создать рабочее место")
    try:
        library = await library_snapshot(file_service, profile.user_id, limit=limit, cursor=cursor)
    except Exception:
        runtime.logger.warning(
            "work activation facet unavailable",
            extra={"component": "library", "failure_code": "unavailable"},
        )
        library = unavailable_library()
    return await ready_work_snapshot(
        {**ref, "user_id": str(profile.user_id)},
        thread_id=thread_id,
        redis=redis,
        library=library,
    )


@router.get("/work-library")
async def account_work_library(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    file_service: FileSaverService = Depends(get_file_saver_service),  # noqa: B008
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    cursor: Annotated[str, Query(max_length=256)] = "",
):
    return await library_snapshot(
        file_service,
        profile.user_id,
        limit=limit,
        offset=offset,
        cursor=cursor,
    )
