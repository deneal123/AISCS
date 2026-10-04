"""Document Forge profile, project, build and artifact routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from application.documents import DocumentProjectError
from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from infrastructure.document_compiler import CompilerFailure

from presentation.routes.contracts import (
    DocumentBuildRequest,
    DocumentCancelRequest,
    DocumentCheckpointLookupRequest,
    DocumentCheckpointRequest,
    DocumentPathRequest,
    DocumentProfileApplyRequest,
    DocumentProjectRequest,
    DocumentSourceRequest,
    DocumentVendorActivateRequest,
    DocumentVendorOverlayRequest,
    DocumentVisualAuditResultRequest,
    OwnerRequest,
)
from presentation.routes.dependencies import WorkspaceRouteDependencies


@dataclass(frozen=True, slots=True)
class DocumentRouteDependencies:
    common: WorkspaceRouteDependencies
    catalog: Any
    projects: Any
    sources: Any
    checkpoints: Any
    vendors: Any
    builds: Any
    vendor_profiles: Any = None


def _status(code: str) -> int:
    if code == "revision_conflict":
        return 409
    if code in {
        "profile_missing",
        "invalid_project",
        "target_path_required",
        "vendor_archive_invalid",
        "vendor_manifest_invalid",
        "vendor_profile_invalid",
        "vendor_unsafe",
        "vendor_integrity",
        "authoring_invalid",
    }:
        return 422
    if code in {"project_exists", "profile_mismatch", "source_changed", "vendor_collision"}:
        return 409
    if code == "audit_busy":
        return 409
    if code in {"build_missing", "authoring_missing"}:
        return 404
    if code in {"audit_unavailable", "visual_unavailable"}:
        return 503
    if code in {"runtime_unavailable", "authoring_publish_failed", "authoring_checkpoint_failed"}:
        return 503
    if code == "artifact_too_large":
        return 413
    if code in {"source_too_large", "vendor_too_large"}:
        return 413
    if code == "vendor_source_unavailable":
        return 503
    return 500


def create_documents_router(deps: DocumentRouteDependencies) -> APIRouter:
    router = APIRouter(tags=["workspace-documents"])

    @router.get("/document-profiles")
    async def profiles(authorization: str | None = Header(default=None)):
        deps.common.auth(authorization)
        return deps.catalog.public_dict()

    @router.post("/workspaces/{workspace_id}/documents/profiles")
    async def workspace_profiles(
        workspace_id: str,
        payload: OwnerRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        _item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        return deps.catalog.public_dict()

    @router.post("/workspaces/{workspace_id}/documents")
    async def create_project(
        workspace_id: str,
        payload: DocumentProjectRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        guarded = await deps.common.coordination_guard(
            payload, "write", path=payload.path, workspace_id=workspace_id
        )
        if deps.common.guard_denied(guarded):
            return guarded
        registry = deps.common.registry()
        if registry is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        try:
            async with registry.operation(item):
                current = await deps.common.revision(item)
                if current != payload.expected_revision:
                    raise DocumentProjectError("revision_conflict")
                result = await deps.projects.create(
                    item,
                    path=payload.path,
                    profile_id=payload.profile_id,
                    mode=payload.mode,
                    locale=payload.locale,
                )
                result["revision"] = await deps.common.revision(item)
                return result
        except DocumentProjectError as exc:
            code = "workspace_conflict" if exc.code == "revision_conflict" else exc.code
            return deps.common.error(code, "document project request failed", _status(exc.code))

    @router.post("/workspaces/{workspace_id}/documents/status")
    async def project_status(
        workspace_id: str,
        payload: DocumentPathRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        registry = deps.common.registry()
        try:
            if registry is None:
                raise DocumentProjectError("runtime_unavailable")
            async with registry.operation(item):
                result = await deps.projects.status(item, payload.path)
                result["vendor_overlays"] = await deps.vendors.list(item, payload.path)
                result["revision"] = await deps.common.revision(item)
            latest = await deps.builds.latest_for_project(registry, item, payload.path)
            if latest is not None:
                result["latest_build"] = latest.public_dict()
            return result
        except DocumentProjectError as exc:
            return deps.common.error(exc.code, "document project unavailable", _status(exc.code))

    @router.post("/workspaces/{workspace_id}/documents/source")
    async def publish_source(
        workspace_id: str,
        payload: DocumentSourceRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        guarded = await deps.common.coordination_guard(
            payload, "write", path=payload.path, workspace_id=workspace_id
        )
        if deps.common.guard_denied(guarded):
            return guarded
        registry = deps.common.registry()
        if registry is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        try:
            async with registry.operation(item):
                current = await deps.common.revision(item)
                if current != payload.expected_revision:
                    raise DocumentProjectError("revision_conflict")
                return await deps.sources.publish(
                    item,
                    path=payload.path,
                    files=payload.files,
                    authoring_version=payload.authoring_version,
                    draft_digest=payload.draft_digest,
                )
        except DocumentProjectError as exc:
            code = "workspace_conflict" if exc.code == "revision_conflict" else exc.code
            return deps.common.error(code, "document source request failed", _status(exc.code))

    @router.post("/workspaces/{workspace_id}/documents/authoring")
    async def document_authoring(
        workspace_id: str,
        payload: DocumentPathRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        if deps.common.registry() is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        try:
            return await deps.projects.authoring_state(item, payload.path)
        except DocumentProjectError as exc:
            return deps.common.error(exc.code, "document authoring unavailable", _status(exc.code))

    @router.post("/workspaces/{workspace_id}/documents/authoring/checkpoint")
    async def checkpoint_authoring(
        workspace_id: str,
        payload: DocumentCheckpointRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        guarded = await deps.common.coordination_guard(
            payload, "write", path=payload.path, workspace_id=workspace_id
        )
        if deps.common.guard_denied(guarded):
            return guarded
        registry = deps.common.registry()
        if registry is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        try:
            async with registry.operation(item):
                current = await deps.common.revision(item)
                if current != payload.expected_revision:
                    raise DocumentProjectError("revision_conflict")
                return await deps.checkpoints.write(
                    item,
                    path=payload.path,
                    checkpoint=payload.checkpoint,
                    revision=current,
                    request_digest=payload.request_digest,
                    evidence_digest=payload.evidence_digest,
                )
        except DocumentProjectError as exc:
            code = "workspace_conflict" if exc.code == "revision_conflict" else exc.code
            return deps.common.error(code, "document checkpoint request failed", _status(exc.code))

    @router.post("/workspaces/{workspace_id}/documents/authoring/checkpoint/latest")
    async def latest_authoring_checkpoint(
        workspace_id: str,
        payload: DocumentCheckpointLookupRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        registry = deps.common.registry()
        if registry is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        try:
            async with registry.operation(item):
                await deps.sources.recover(item)
                result = await deps.checkpoints.latest(
                    item,
                    request_digest=payload.request_digest,
                    evidence_digest=payload.evidence_digest,
                )
                if result is not None:
                    result["revision"] = await deps.common.revision(item)
            return result or {"outcome": "absent"}
        except DocumentProjectError as exc:
            return deps.common.error(exc.code, "document checkpoint unavailable", _status(exc.code))

    @router.post("/workspaces/{workspace_id}/documents/profile")
    async def apply_profile(
        workspace_id: str,
        payload: DocumentProfileApplyRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        guarded = await deps.common.coordination_guard(
            payload, "write", path=payload.path, workspace_id=workspace_id
        )
        if deps.common.guard_denied(guarded):
            return guarded
        registry = deps.common.registry()
        if registry is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        try:
            async with registry.operation(item):
                current = await deps.common.revision(item)
                if current != payload.expected_revision:
                    raise DocumentProjectError("revision_conflict")
                result = await deps.projects.apply_profile(
                    item,
                    path=payload.path,
                    profile_id=payload.profile_id,
                    mode=payload.mode,
                    locale=payload.locale,
                    target_path=payload.target_path,
                )
                result["revision"] = await deps.common.revision(item)
                return result
        except DocumentProjectError as exc:
            code = "workspace_conflict" if exc.code == "revision_conflict" else exc.code
            return deps.common.error(code, "document profile request failed", _status(exc.code))

    @router.post("/workspaces/{workspace_id}/documents/vendor")
    async def apply_vendor_overlay(
        workspace_id: str,
        payload: DocumentVendorOverlayRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        guarded = await deps.common.coordination_guard(
            payload,
            "write",
            path=payload.path,
            workspace_id=workspace_id,
        )
        if deps.common.guard_denied(guarded):
            return guarded
        registry = deps.common.registry()
        if registry is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        try:
            async with registry.operation(item):
                result = await deps.vendors.apply(
                    item,
                    path=payload.path,
                    source_url=payload.source.url,
                    source_sha256=payload.source.sha256,
                    expected_revision=payload.expected_revision,
                )
                result["revision"] = await deps.common.revision(item)
                return result
        except DocumentProjectError as exc:
            code = "workspace_conflict" if exc.code == "revision_conflict" else exc.code
            return deps.common.error(code, "vendor overlay request failed", _status(exc.code))

    @router.post("/workspaces/{workspace_id}/documents/vendor/activate")
    async def activate_vendor_profile(
        workspace_id: str,
        payload: DocumentVendorActivateRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        guarded = await deps.common.coordination_guard(
            payload,
            "write",
            path=payload.path,
            workspace_id=workspace_id,
        )
        if deps.common.guard_denied(guarded):
            return guarded
        registry = deps.common.registry()
        if registry is None or deps.vendor_profiles is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        try:
            return await deps.vendor_profiles.activate(
                registry,
                item,
                path=payload.path,
                package_id=payload.package_id,
                target_path=payload.target_path,
                expected_revision=payload.expected_revision,
            )
        except DocumentProjectError as exc:
            code = "workspace_conflict" if exc.code == "revision_conflict" else exc.code
            return deps.common.error(code, "vendor profile activation failed", _status(exc.code))

    @router.post("/workspaces/{workspace_id}/documents/builds")
    async def start_build(
        workspace_id: str,
        payload: DocumentBuildRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        guarded = await deps.common.coordination_guard(
            payload, "exec", path=payload.path, workspace_id=workspace_id
        )
        if deps.common.guard_denied(guarded):
            return guarded
        registry = deps.common.registry()
        if registry is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        try:
            build = await deps.builds.start(
                registry,
                item,
                project_path=payload.path,
                expected_revision=payload.expected_revision,
                final=payload.final,
            )
            return build.public_dict()
        except DocumentProjectError as exc:
            code = "workspace_conflict" if exc.code == "revision_conflict" else exc.code
            return deps.common.error(code, "document build could not start", _status(exc.code))
        except CompilerFailure as exc:
            return deps.common.error(exc.code, "document runtime unavailable", _status(exc.code))

    @router.post("/workspaces/{workspace_id}/documents/builds/{build_id}")
    async def build_status(
        workspace_id: str,
        build_id: str,
        payload: OwnerRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        registry = deps.common.registry()
        if registry is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        build = await deps.builds.find(registry, item, build_id)
        return (
            build.public_dict()
            if build is not None
            else deps.common.error("not_found", "document build not found", 404)
        )

    @router.post("/workspaces/{workspace_id}/documents/builds/{build_id}/cancel")
    async def cancel_build(
        workspace_id: str,
        build_id: str,
        payload: DocumentCancelRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        guarded = await deps.common.coordination_guard(payload, "exec", workspace_id=workspace_id)
        if deps.common.guard_denied(guarded):
            return guarded
        registry = deps.common.registry()
        if registry is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        build = await deps.builds.cancel(registry, item, workspace_id, build_id)
        return (
            build.public_dict()
            if build is not None
            else deps.common.error("not_found", "document build not found", 404)
        )

    @router.post("/workspaces/{workspace_id}/documents/builds/{build_id}/artifacts/{artifact_id}")
    async def download_artifact(
        workspace_id: str,
        build_id: str,
        artifact_id: str,
        payload: OwnerRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        try:
            registry = deps.common.registry()
            if registry is None:
                raise CompilerFailure("runtime_unavailable")
            found = await deps.builds.artifact_stream(registry, item, build_id, artifact_id)
        except CompilerFailure as exc:
            return deps.common.error(exc.code, "document artifact unavailable", _status(exc.code))
        if found is None:
            return deps.common.error("not_found", "document artifact not found", 404)
        artifact, stream = found
        return StreamingResponse(
            stream,
            media_type=artifact.mime_type,
            headers={
                "Content-Disposition": f'attachment; filename="{artifact.filename}"',
                "X-Artifact-Sha256": artifact.sha256,
                "Content-Length": str(artifact.size),
            },
        )

    @router.post("/workspaces/{workspace_id}/documents/builds/{build_id}/visual-audit/claim")
    async def claim_visual_audit(
        workspace_id: str,
        build_id: str,
        payload: DocumentCancelRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        guarded = await deps.common.coordination_guard(payload, "write", workspace_id=workspace_id)
        if deps.common.guard_denied(guarded):
            return guarded
        registry = deps.common.registry()
        if registry is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        try:
            build = await deps.builds.claim_visual_audit(registry, item, build_id)
            pdf = next((entry for entry in build.artifacts if entry.role == "pdf"), None)
            if pdf is None:
                return deps.common.error("artifact_invalid", "visual audit unavailable", 500)
            return {
                **build.public_dict(),
                "audit": {
                    "source_digest": build.source_digest,
                    "artifact_sha256": pdf.sha256,
                    "page_count": build.page_count,
                    "profile_id": build.profile_id,
                    "profile_version": build.profile_version,
                    "block_pages": [
                        {"page": page, "block_ids": list(block_ids)}
                        for page, block_ids in sorted(build.page_blocks.items())
                    ],
                },
            }
        except DocumentProjectError as exc:
            return deps.common.error(exc.code, "visual audit unavailable", _status(exc.code))

    @router.post("/workspaces/{workspace_id}/documents/builds/{build_id}/visual-pages")
    async def visual_pages(
        workspace_id: str,
        build_id: str,
        payload: OwnerRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        registry = deps.common.registry()
        if registry is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        try:
            metadata, stream = await deps.builds.visual_bundle_stream(registry, item, build_id)
        except DocumentProjectError as exc:
            return deps.common.error(exc.code, "visual pages unavailable", _status(exc.code))
        return StreamingResponse(
            stream,
            media_type="application/x-tar",
            headers={
                "Content-Length": str(metadata["bundle_size"]),
                "X-Artifact-Sha256": str(metadata["bundle_sha256"]),
                "X-Document-Source-Digest": str(metadata["source_digest"]),
                "X-Document-Pdf-Sha256": str(metadata["artifact_sha256"]),
                "X-Document-Page-Count": str(metadata["page_count"]),
                "X-Document-Profile": str(metadata["profile_id"]),
                "X-Document-Profile-Version": str(metadata["profile_version"]),
            },
        )

    @router.post("/workspaces/{workspace_id}/documents/builds/{build_id}/visual-audit/result")
    async def complete_visual_audit(
        workspace_id: str,
        build_id: str,
        payload: DocumentVisualAuditResultRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        guarded = await deps.common.coordination_guard(payload, "write", workspace_id=workspace_id)
        if deps.common.guard_denied(guarded):
            return guarded
        registry = deps.common.registry()
        if registry is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        try:
            build = await deps.builds.complete_visual_audit(
                registry,
                item,
                build_id,
                source_digest=payload.source_digest,
                artifact_sha256=payload.artifact_sha256,
                passed=payload.passed,
                retryable=payload.retryable,
                audit_version=payload.audit_version,
                diagnostics=payload.diagnostics,
            )
            return build.public_dict()
        except DocumentProjectError as exc:
            return deps.common.error(exc.code, "visual audit result rejected", _status(exc.code))

    @router.post("/workspaces/{workspace_id}/documents/builds/{build_id}/visual-pages/{page}")
    async def visual_page(
        workspace_id: str,
        build_id: str,
        page: int,
        payload: OwnerRequest,
        authorization: str | None = Header(default=None),
    ):
        deps.common.auth(authorization)
        item, failure = deps.common.owned(workspace_id, payload)
        if failure is not None:
            return failure
        registry = deps.common.registry()
        if registry is None:
            return deps.common.error("workspace_unavailable", "workspace is unavailable", 503)
        try:
            size, digest, stream = await deps.builds.visual_page_stream(
                registry, item, build_id, page
            )
        except DocumentProjectError as exc:
            return deps.common.error(exc.code, "visual page unavailable", _status(exc.code))
        return StreamingResponse(
            stream,
            media_type="image/png",
            headers={"Content-Length": str(size), "X-Artifact-Sha256": digest},
        )

    return router
