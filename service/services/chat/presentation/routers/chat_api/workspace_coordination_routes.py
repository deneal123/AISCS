"""Lease, collaboration, write, and run-control workspace routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from service.composition.state import get_chat_application_service, get_optional_redis_client
from service.models.auth_models import AuthProfile
from service.services.chat.application.chat_application_service import ChatApplicationService
from service.services.chat.presentation.routers.chat_api.workspace_contracts import (
    ControlRequest,
    IssueCreateRequest,
    IssueUpdateRequest,
    LeaseRequest,
    WriteRequest,
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


@router.post("/{thread_id}/workspace/leases/acquire")
async def acquire_workspace_lease(
    thread_id: str,
    payload: Annotated[LeaseRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    workspace_session: WorkspaceSessionHeader = None,
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    try:
        capability = runtime._request_ui_capability(ref, str(profile.user_id), workspace_session)
        lease = await runtime._collaboration(ref, redis).acquire_lease(
            runtime.verify_capability(capability), payload.path
        )
        return lease.public()
    except runtime.CollaborationError as exc:
        raise runtime._collaboration_http_error(exc) from exc


@router.post("/{thread_id}/workspace/leases/renew")
async def renew_workspace_lease(
    thread_id: str,
    payload: Annotated[LeaseRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    workspace_session: WorkspaceSessionHeader = None,
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    if payload.fence is None:
        raise HTTPException(status_code=422, detail="Для продления правки нужна текущая lease")
    try:
        capability = runtime.verify_capability(
            runtime._request_ui_capability(ref, str(profile.user_id), workspace_session)
        )
        lease = await runtime._collaboration(ref, redis).renew_lease(
            capability, payload.path, payload.fence
        )
        return lease.public()
    except runtime.CollaborationError as exc:
        raise runtime._collaboration_http_error(exc) from exc


@router.post("/{thread_id}/workspace/leases/release")
async def release_workspace_lease(
    thread_id: str,
    payload: Annotated[LeaseRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    workspace_session: WorkspaceSessionHeader = None,
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    try:
        capability = runtime.verify_capability(
            runtime._request_ui_capability(ref, str(profile.user_id), workspace_session)
        )
        released = await runtime._collaboration(ref, redis).release_lease(
            capability, payload.path, payload.fence
        )
        return {"released": released}
    except runtime.CollaborationError as exc:
        raise runtime._collaboration_http_error(exc) from exc


@router.post("/{thread_id}/workspace/write")
async def write_workspace_file(
    thread_id: str,
    payload: Annotated[WriteRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    workspace_session: WorkspaceSessionHeader = None,
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    try:
        capability = runtime._request_ui_capability(ref, str(profile.user_id), workspace_session)
        parsed = runtime.verify_capability(capability)
        store = runtime._collaboration(ref, redis)
        check = await store.preflight(
            parsed, mutation="write", path=payload.path, fence=payload.fence
        )
        async with runtime._alive(redis, thread_id):
            result = await runtime.workspace_client.write_file(
                ref,
                payload.path,
                payload.content,
                payload.expected_revision,
                fence=check["fence"],
                coordination_capability=capability,
            )
        if not result or not result.get("written"):
            raise runtime.CollaborationConflict("workspace write was not committed")
        revision = str(result.get("revision") or "")
        await store.mark_stale(path=payload.path, revision=revision)
        await store.record_activity("file_saved")
        return {
            "written": True,
            "path": payload.path,
            "revision": revision,
            "fence": check["fence"],
        }
    except runtime.workspace_client.WorkspaceConflict as exc:
        raise HTTPException(
            status_code=409, detail="Рабочее место изменилось; обновите файл"
        ) from exc
    except runtime.CollaborationError as exc:
        raise runtime._collaboration_http_error(exc) from exc


@router.get("/{thread_id}/workspace/issues")
async def workspace_issues(
    thread_id: str,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    try:
        return {
            "issues": await runtime._collaboration(ref, redis).list_issues(include_resolved=True)
        }
    except runtime.CollaborationError as exc:
        raise runtime._collaboration_http_error(exc) from exc


@router.post("/{thread_id}/workspace/issues")
async def create_workspace_issue(
    thread_id: str,
    payload: Annotated[IssueCreateRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    try:
        return await runtime._collaboration(ref, redis).create_issue(
            runtime.verify_capability(runtime._ui_capability(ref, str(profile.user_id))),
            path=payload.path,
            start_line=payload.start_line,
            end_line=payload.end_line,
            revision=payload.revision,
            title=payload.title,
            body=payload.body,
        )
    except runtime.CollaborationError as exc:
        raise runtime._collaboration_http_error(exc) from exc


@router.patch("/{thread_id}/workspace/issues/{issue_id}")
async def update_workspace_issue(
    thread_id: str,
    issue_id: str,
    payload: Annotated[IssueUpdateRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    try:
        return await runtime._collaboration(ref, redis).update_issue(
            runtime.verify_capability(runtime._ui_capability(ref, str(profile.user_id))),
            issue_id,
            status=payload.status,
            revision=payload.revision,
            start_line=payload.start_line,
            end_line=payload.end_line,
        )
    except runtime.CollaborationError as exc:
        raise runtime._collaboration_http_error(exc) from exc


@router.post("/{thread_id}/workspace/control")
async def workspace_control(
    thread_id: str,
    payload: Annotated[ControlRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    try:
        store = runtime._collaboration(ref, redis)
        state = await store.set_control(payload.action)
        if payload.action == "cancel":
            await runtime._request_active_run_cancellation(store, redis)
        return {"control": state}
    except runtime.CollaborationError as exc:
        raise runtime._collaboration_http_error(exc) from exc


@router.post("/{thread_id}/workflows/pin")
async def pin_workflow(
    thread_id: str,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
):
    await service.ensure_thread_owner(thread_id, str(profile.user_id))
    raise HTTPException(status_code=410, detail="workflow_catalog_autonomous")
