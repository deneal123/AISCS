"""Owner-checked Document Forge routes for Work Hub."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from service.composition.state import (
    get_chat_application_service,
    get_file_saver_service,
    get_optional_redis_client,
)
from service.models.auth_models import AuthProfile
from service.services.chat.application.chat_application_service import ChatApplicationService
from service.services.chat.presentation.routers.chat_api.workspace_contracts import (
    DocumentBuildRequest,
    DocumentCancelRequest,
    DocumentPathRequest,
    DocumentProfileApplyRequest,
    DocumentProjectRequest,
    DocumentSourceRequest,
    DocumentVendorActivateRequest,
    DocumentVendorOverlayRequest,
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


def _publication_descriptor(
    *, build_id: str, artifact_id: str, status: dict, artifact: dict
) -> dict:
    """Project a sidecar artifact into the canonical outbox-validator input."""

    return {
        "build_id": build_id,
        "artifact_id": artifact_id,
        "role": str(artifact.get("role") or ""),
        "source_digest": str(status.get("source_digest") or ""),
        "sha256": str(artifact.get("sha256") or ""),
        "size": int(artifact.get("size") or 0),
        "filename": str(artifact.get("filename") or "document.pdf"),
        "mime_type": str(artifact.get("mime_type") or ""),
    }


async def _scoped_ref(service, thread_id, profile, redis, workspace_session):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    capability = runtime._request_ui_capability(ref, str(profile.user_id), workspace_session)
    return runtime, ref, {**ref, "coordination_capability": capability}


@router.get("/{thread_id}/workspace/document-profiles")
async def document_profiles(
    thread_id: str,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
):
    await service.ensure_thread_owner(thread_id, str(profile.user_id))
    runtime = _runtime()
    try:
        return await runtime.workspace_client.document_profiles()
    except runtime.workspace_client.WorkspaceUnavailable as exc:
        raise HTTPException(status_code=503, detail="document_profiles_unavailable") from exc


@router.post("/{thread_id}/workspace/documents")
async def create_document_project(
    thread_id: str,
    payload: Annotated[DocumentProjectRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    workspace_session: WorkspaceSessionHeader = None,
):
    runtime, ref, scoped = await _scoped_ref(service, thread_id, profile, redis, workspace_session)
    try:
        async with runtime._alive(redis, thread_id):
            result = await runtime.workspace_client.create_document_project(
                scoped,
                path=payload.path,
                profile_id=payload.profile_id,
                mode=payload.mode,
                locale=payload.locale,
                expected_revision=payload.expected_revision,
                fence=payload.fence,
            )
    except runtime.workspace_client.WorkspaceConflict as exc:
        raise HTTPException(status_code=409, detail="workspace_conflict") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=503, detail="document_project_unavailable")
    return result


@router.post("/{thread_id}/workspace/documents/status")
async def document_project_status(
    thread_id: str,
    payload: Annotated[DocumentPathRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    async with runtime._alive(redis, thread_id):
        result = await runtime.workspace_client.document_project_status(ref, path=payload.path)
    if not isinstance(result, dict):
        raise HTTPException(status_code=404, detail="document_project_not_found")
    return result


@router.post("/{thread_id}/workspace/documents/authoring")
async def document_authoring_state(
    thread_id: str,
    payload: Annotated[DocumentPathRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    async with runtime._alive(redis, thread_id):
        result = await runtime.workspace_client.document_authoring_state(ref, path=payload.path)
    if not isinstance(result, dict):
        raise HTTPException(status_code=404, detail="document_authoring_not_found")
    return result


@router.post("/{thread_id}/workspace/documents/source")
async def publish_document_source(
    thread_id: str,
    payload: Annotated[DocumentSourceRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    workspace_session: WorkspaceSessionHeader = None,
):
    """Publish a renderer-owned source graph without exposing sidecar credentials."""

    runtime, _ref, scoped = await _scoped_ref(service, thread_id, profile, redis, workspace_session)
    try:
        parsed = runtime.verify_capability(str(scoped.get("coordination_capability") or ""))
        store = runtime._collaboration(scoped, redis)
        checked = await store.preflight(
            parsed,
            mutation="write",
            path=payload.path,
            fence=payload.fence,
        )
        async with runtime._alive(redis, thread_id):
            result = await runtime.workspace_client.publish_document_source(
                scoped,
                path=payload.path,
                files=payload.files,
                authoring_version=payload.authoring_version,
                draft_digest=payload.draft_digest,
                expected_revision=payload.expected_revision,
                fence=int(checked["fence"]),
            )
    except runtime.workspace_client.WorkspaceConflict as exc:
        raise HTTPException(status_code=409, detail="workspace_conflict") from exc
    except runtime.workspace_client.WorkspaceRequestRejected as exc:
        status = {"source_too_large": 413}.get(exc.code, 422)
        raise HTTPException(status_code=status, detail=exc.code) from exc
    except runtime.CollaborationError as exc:
        raise runtime._collaboration_http_error(exc) from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=503, detail="document_source_unavailable")
    revision = str(result.get("revision") or "")
    if result.get("revision_changed"):
        await store.mark_stale(path=payload.path, revision=revision)
        await store.record_activity("file_saved")
    return {
        "outcome": "published",
        "revision": revision,
        "revision_changed": bool(result.get("revision_changed")),
        "authoring_version": int(result.get("authoring_version") or 0),
        "draft_digest": str(result.get("draft_digest") or ""),
        "file_count": int(result.get("file_count") or 0),
    }


@router.post("/{thread_id}/workspace/documents/profile")
async def apply_document_profile(
    thread_id: str,
    payload: Annotated[DocumentProfileApplyRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    workspace_session: WorkspaceSessionHeader = None,
):
    runtime, _ref, scoped = await _scoped_ref(service, thread_id, profile, redis, workspace_session)
    try:
        async with runtime._alive(redis, thread_id):
            result = await runtime.workspace_client.apply_document_profile(
                scoped,
                path=payload.path,
                target_path=payload.target_path,
                profile_id=payload.profile_id,
                mode=payload.mode,
                locale=payload.locale,
                expected_revision=payload.expected_revision,
                fence=payload.fence,
            )
    except runtime.workspace_client.WorkspaceConflict as exc:
        raise HTTPException(status_code=409, detail="workspace_conflict") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=503, detail="document_profile_unavailable")
    return result


@router.post("/{thread_id}/workspace/documents/vendor/{file_id}")
async def apply_document_vendor_overlay(
    thread_id: str,
    file_id: UUID,
    payload: Annotated[DocumentVendorOverlayRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    file_service: FileSaverService = Depends(get_file_saver_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    workspace_session: WorkspaceSessionHeader = None,
):
    runtime, _ref, scoped = await _scoped_ref(service, thread_id, profile, redis, workspace_session)
    try:
        source = await file_service.resolve_chat_library_import(
            profile.user_id, file_id, expiry_sec=120
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="library_file_unavailable") from exc
    if not str(source.get("name") or "").lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="vendor_archive_required")
    try:
        parsed = runtime.verify_capability(str(scoped.get("coordination_capability") or ""))
        store = runtime._collaboration(scoped, redis)
        checked = await store.preflight(
            parsed,
            mutation="write",
            path=payload.path,
            fence=payload.fence,
        )
        async with runtime._alive(redis, thread_id):
            result = await runtime.workspace_client.apply_document_vendor_overlay(
                scoped,
                path=payload.path,
                source=source,
                expected_revision=payload.expected_revision,
                fence=int(checked["fence"]),
            )
    except runtime.workspace_client.WorkspaceConflict as exc:
        raise HTTPException(status_code=409, detail="workspace_conflict") from exc
    except runtime.workspace_client.WorkspaceRequestRejected as exc:
        status = {
            "vendor_collision": 409,
            "vendor_too_large": 413,
            "vendor_source_unavailable": 503,
        }.get(exc.code, 422)
        raise HTTPException(status_code=status, detail=exc.code) from exc
    except runtime.CollaborationError as exc:
        raise runtime._collaboration_http_error(exc) from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=422, detail="vendor_overlay_invalid")
    if result.get("revision_changed"):
        revision = str(result.get("revision") or "")
        await store.mark_stale(path=payload.path, revision=revision)
        await store.record_activity("file_saved")
    return {
        "outcome": "imported" if result.get("outcome") == "imported" else "kept",
        "revision": str(result.get("revision") or ""),
        "overlay": {
            key: result.get("overlay", {}).get(key)
            for key in ("package_id", "version", "license", "file_count", "trusted")
        },
    }


@router.post("/{thread_id}/workspace/documents/vendor/{package_id}/activate")
async def activate_document_vendor_profile(
    thread_id: str,
    package_id: str,
    payload: Annotated[DocumentVendorActivateRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    workspace_session: WorkspaceSessionHeader = None,
):
    if not package_id or len(package_id) > 64:
        raise HTTPException(status_code=422, detail="vendor_profile_invalid")
    runtime, _ref, scoped = await _scoped_ref(service, thread_id, profile, redis, workspace_session)
    try:
        parsed = runtime.verify_capability(str(scoped.get("coordination_capability") or ""))
        store = runtime._collaboration(scoped, redis)
        checked = await store.preflight(
            parsed,
            mutation="write",
            path=payload.path,
            fence=payload.fence,
        )
        async with runtime._alive(redis, thread_id):
            result = await runtime.workspace_client.activate_document_vendor_profile(
                scoped,
                path=payload.path,
                package_id=package_id,
                target_path=payload.target_path,
                expected_revision=payload.expected_revision,
                fence=int(checked["fence"]),
            )
    except runtime.workspace_client.WorkspaceConflict as exc:
        raise HTTPException(status_code=409, detail="workspace_conflict") from exc
    except runtime.workspace_client.WorkspaceRequestRejected as exc:
        status = 409 if exc.code in {"vendor_collision", "source_changed"} else 422
        raise HTTPException(status_code=status, detail=exc.code) from exc
    except runtime.CollaborationError as exc:
        raise runtime._collaboration_http_error(exc) from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=503, detail="vendor_profile_unavailable")
    revision = str(result.get("revision") or "")
    if result.get("revision_changed"):
        await store.mark_stale(path=payload.path, revision=revision)
        await store.record_activity("file_saved")
    effective = (
        result.get("effective_profile") if isinstance(result.get("effective_profile"), dict) else {}
    )
    return {
        "outcome": "cloned",
        "path": str(result.get("path") or ""),
        "source_path": str(result.get("source_path") or ""),
        "revision": revision,
        "revision_changed": bool(result.get("revision_changed")),
        "content_status": (
            "copied" if result.get("content_status") == "copied" else "content_migration_required"
        ),
        "effective_profile": {
            key: effective.get(key)
            for key in (
                "base_profile_id",
                "vendor_package_id",
                "content_contract",
                "paper",
                "orientation",
                "max_pages",
            )
        },
    }


@router.post("/{thread_id}/workspace/documents/builds")
async def start_document_build(
    thread_id: str,
    payload: Annotated[DocumentBuildRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    workspace_session: WorkspaceSessionHeader = None,
):
    runtime, _ref, scoped = await _scoped_ref(service, thread_id, profile, redis, workspace_session)
    try:
        async with runtime._alive(redis, thread_id):
            result = await runtime.workspace_client.start_document_build(
                scoped,
                path=payload.path,
                expected_revision=payload.expected_revision,
                fence=payload.fence,
                final=payload.final,
            )
    except runtime.workspace_client.WorkspaceConflict as exc:
        raise HTTPException(status_code=409, detail="workspace_conflict") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=503, detail="document_build_unavailable")
    return result


@router.post("/{thread_id}/workspace/documents/builds/{build_id}")
async def document_build_status(
    thread_id: str,
    build_id: str,
    request: Request,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    async with runtime._alive(redis, thread_id):
        result = await runtime.workspace_client.document_build_status(ref, build_id=build_id)
    if not isinstance(result, dict):
        raise HTTPException(status_code=404, detail="document_build_not_found")
    from service.composition.state import get_app_container
    from service.services.chat.persistence.document_publications import state_for_build

    connector = get_app_container(request).infra.pg_connector
    async with connector.get_session_context() as session:
        result["publication_state"] = await state_for_build(
            session, user_id=profile.user_id, build_id=build_id
        )
    return result


@router.post("/{thread_id}/workspace/documents/builds/{build_id}/cancel")
async def cancel_document_build(
    thread_id: str,
    build_id: str,
    payload: Annotated[DocumentCancelRequest, Body(...)],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
    workspace_session: WorkspaceSessionHeader = None,
):
    runtime, _ref, scoped = await _scoped_ref(service, thread_id, profile, redis, workspace_session)
    result = await runtime.workspace_client.cancel_document_build(
        scoped, build_id=build_id, fence=payload.fence
    )
    if not isinstance(result, dict):
        raise HTTPException(status_code=404, detail="document_build_not_found")
    return result


@router.post("/{thread_id}/workspace/documents/builds/{build_id}/artifacts/{artifact_id}")
async def download_document_artifact(
    thread_id: str,
    build_id: str,
    artifact_id: str,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    try:
        async with runtime._alive(redis, thread_id):
            download = await runtime.workspace_client.stream_document_artifact(
                ref, build_id=build_id, artifact_id=artifact_id
            )
    except runtime.workspace_client.DocumentArtifactMissing as exc:
        raise HTTPException(status_code=404, detail="document_artifact_not_found") from exc
    return StreamingResponse(
        download.chunks(),
        media_type=download.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{download.filename}"',
            "Content-Length": str(download.size),
            "X-Artifact-Sha256": download.sha256,
        },
    )


@router.post("/{thread_id}/workspace/documents/builds/{build_id}/artifacts/{artifact_id}/publish")
async def publish_document_artifact(
    thread_id: str,
    build_id: str,
    artifact_id: str,
    request: Request,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    runtime = _runtime()
    ref = await runtime._ref(service, thread_id, str(profile.user_id), redis)
    async with runtime._alive(redis, thread_id):
        status = await runtime.workspace_client.document_build_status(ref, build_id=build_id)
    if not isinstance(status, dict) or status.get("state") not in {"visual_pending", "ready"}:
        raise HTTPException(status_code=409, detail="document_build_not_publishable")
    artifact = next(
        (
            item
            for item in status.get("artifacts") or []
            if isinstance(item, dict) and str(item.get("artifact_id")) == artifact_id
        ),
        None,
    )
    if not artifact or artifact.get("mime_type") not in {"application/pdf", "application/zip"}:
        raise HTTPException(status_code=422, detail="artifact_type_invalid")
    from service.composition.state import get_app_container
    from service.services.chat.persistence.document_publications import (
        enqueue,
        normalize_descriptors,
    )

    descriptor = _publication_descriptor(
        build_id=build_id,
        artifact_id=artifact_id,
        status=status,
        artifact=artifact,
    )
    descriptors = normalize_descriptors([descriptor])
    if not descriptors:
        raise HTTPException(status_code=422, detail="artifact_contract_invalid")
    connector = get_app_container(request).infra.pg_connector
    async with connector.get_session_context() as session:
        jobs = await enqueue(
            session,
            user_id=profile.user_id,
            thread_id=thread_id,
            workspace_id=str(ref.get("workspace_id") or ""),
            billing_job_id=f"document:{build_id}:{artifact_id}",
            descriptors=descriptors,
            attach_to_latest=False,
            initial_status=(
                "pending_audit" if status.get("state") == "visual_pending" else "pending_delivery"
            ),
        )
        await session.commit()
    try:
        from service.infrastructure.messaging.tasks import deliver_document_publications

        deliver_document_publications.delay()
    except Exception:
        pass
    row = jobs[0] if jobs else {}
    return JSONResponse(
        status_code=202,
        content={
            "outcome": "queued" if row.get("status") != "delivered" else "reused",
            "publication_state": row.get("status") or "pending_delivery",
            **({"file_id": str(row["user_file_id"])} if row.get("user_file_id") else {}),
        },
    )
