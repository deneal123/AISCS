"""Library copy and direct-upload orchestration for Work Hub."""

from __future__ import annotations

import contextlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, UploadFile

from service.composition.state import (
    get_chat_application_service,
    get_file_saver_service,
    get_optional_redis_client,
)
from service.models.auth_models import AuthProfile
from service.services.chat.application.chat_application_service import ChatApplicationService
from service.services.chat.presentation.routers.chat_api.work_intake import (
    WorkspaceIntakeDeferred,
    persist_and_import_uploaded_file,
)
from service.services.chat.presentation.routers.chat_api.workspace_contracts import (
    LibraryCopyRequest,
)
from service.services.chat.presentation.routers.chat_api.workspace_metrics import (
    WorkspaceMetricsRoute,
)
from service.services.files.application.file_saver_service import FileSaverService
from service.shared.security.auth_checker import check_auth

router = APIRouter(route_class=WorkspaceMetricsRoute)
WorkspaceSessionHeader = Annotated[str | None, Header(alias="X-Workspace-Session")]


def _runtime():
    from service.services.chat.presentation.routers.chat_api import workspace_api

    return workspace_api


@router.post("/{thread_id}/work/library/{file_id}/copy")
async def copy_library_file_to_workspace(
    thread_id: str,
    file_id: UUID,
    payload: Annotated[LibraryCopyRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    file_service: FileSaverService = Depends(get_file_saver_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    workspace_session: WorkspaceSessionHeader = None,
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    try:
        source = await file_service.resolve_chat_library_import(
            profile.user_id, file_id, expiry_sec=120
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Файл библиотеки недоступен") from exc
    try:
        capability = runtime._request_ui_capability(ref, str(profile.user_id), workspace_session)
        parsed = runtime.verify_capability(capability)
        store = runtime._collaboration(ref, redis)
        check = await store.preflight(
            parsed, mutation="import", path=source["name"], fence=payload.fence
        )
        scoped_ref = {**ref, "coordination_capability": capability}
        async with runtime._alive(redis, thread_id):
            result = await runtime.workspace_client.import_into_workspace(
                scoped_ref,
                [source],
                expected_revision=payload.expected_revision,
                fence=check["fence"],
            )
        if not isinstance(result, dict):
            raise runtime.CollaborationUnavailable("workspace import is unavailable")
        imported = int(result.get("imported") or 0)
        kept = int(result.get("kept") or 0)
        revision = str(result.get("revision") or "")
        if imported:
            await store.mark_stale(path=source["name"], revision=revision)
            await store.record_activity("library_copied")
            return {"outcome": "imported", "revision": revision}
        if kept:
            return {"outcome": "kept", "revision": revision}
        return {"outcome": "failed", "revision": revision}
    except runtime.workspace_client.WorkspaceConflict as exc:
        raise HTTPException(
            status_code=409, detail="Рабочее место изменилось; обновите данные"
        ) from exc
    except runtime.CollaborationError as exc:
        raise runtime._collaboration_http_error(exc) from exc


async def _import_uploaded_source(
    *,
    source: dict,
    thread_id: str,
    user_id: str,
    redis,
    expected_revision: str,
    fence: int,
    workspace_session: str | None,
) -> dict | None:
    runtime = _runtime()
    ref = await runtime.workspace_client.read_binding(redis, thread_id)
    if not ref:
        ref = await runtime.workspace_client.ensure_workspace_explicit(redis, thread_id, user_id)
    if not ref:
        raise WorkspaceIntakeDeferred("unavailable")
    ref = {**ref, "user_id": user_id, "thread_id": thread_id}
    store = None
    parsed = None
    owned_lease = None
    try:
        capability = runtime._request_ui_capability(ref, user_id, workspace_session)
        parsed = runtime.verify_capability(capability)
        store = runtime._collaboration(ref, redis)
        if fence <= 0:
            owned_lease = await store.acquire_lease(parsed, source["name"])
            checked_fence = owned_lease.fence
            revision = str((await runtime.workspace_client.view(ref)).get("revision") or "")
        else:
            checked = await store.preflight(
                parsed, mutation="import", path=source["name"], fence=fence
            )
            checked_fence = int(checked["fence"])
            revision = expected_revision
        result = await runtime.workspace_client.import_into_workspace(
            {**ref, "coordination_capability": capability},
            [source],
            expected_revision=revision,
            fence=checked_fence,
        )
        if isinstance(result, dict) and int(result.get("imported") or 0):
            next_revision = str(result.get("revision") or "")
            await store.mark_stale(path=source["name"], revision=next_revision)
            await store.record_activity("library_copied")
        return result
    except runtime.workspace_client.WorkspaceGone as exc:
        await runtime.workspace_client.forget_binding(redis, thread_id)
        raise WorkspaceIntakeDeferred("expired") from exc
    except runtime.workspace_client.WorkspaceConflict as exc:
        raise WorkspaceIntakeDeferred("conflict") from exc
    except (runtime.CollaborationPaused, runtime.CollaborationConflict) as exc:
        raise WorkspaceIntakeDeferred("locked") from exc
    except (runtime.workspace_client.WorkspaceUnavailable, runtime.CollaborationUnavailable) as exc:
        raise WorkspaceIntakeDeferred("unavailable") from exc
    except HTTPException as exc:
        raise WorkspaceIntakeDeferred("unavailable") from exc
    finally:
        if owned_lease is not None and store is not None and parsed is not None:
            with contextlib.suppress(runtime.CollaborationError):
                await store.release_lease(parsed, source["name"], owned_lease.fence)


@router.post("/{thread_id}/work/upload")
async def upload_file_to_workspace(
    thread_id: str,
    file: Annotated[UploadFile, File(...)],
    expected_revision: Annotated[str, Form(max_length=64)],
    fence: Annotated[int, Form(ge=0)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    file_service: FileSaverService = Depends(get_file_saver_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    upload_intent_id: Annotated[UUID | None, Form()] = None,
    workspace_session: WorkspaceSessionHeader = None,
):
    await service.ensure_thread_owner(thread_id, str(profile.user_id))
    if bool(expected_revision) != bool(fence > 0):
        raise HTTPException(status_code=422, detail="revision_and_fence_must_be_paired")

    async def import_workspace(source: dict) -> dict | None:
        return await _import_uploaded_source(
            source=source,
            thread_id=thread_id,
            user_id=str(profile.user_id),
            redis=redis,
            expected_revision=expected_revision,
            fence=fence,
            workspace_session=workspace_session,
        )

    return await persist_and_import_uploaded_file(
        file=file,
        user_id=profile.user_id,
        file_service=file_service,
        import_workspace=import_workspace,
        upload_intent_id=upload_intent_id,
    )
