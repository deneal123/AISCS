"""Document Forge boundary for the workspace sidecar.

This module owns document-specific payloads and the bounded artifact stream.  The
general workspace client retains lifecycle/files/history operations and re-exports
these names while existing consumers migrate without a wire-contract change.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

MAX_DOCUMENT_ARTIFACT_BYTES = 64 * 1024 * 1024


class DocumentArtifactMissing(Exception):
    """The workspace exists, but the requested build artifact is unavailable."""


@dataclass(slots=True)
class DocumentArtifactDownload:
    client: httpx.AsyncClient
    response: httpx.Response
    filename: str
    mime_type: str
    size: int
    sha256: str

    async def chunks(self) -> AsyncIterator[bytes]:
        """Yield a bounded stream and verify the declared digest at EOF."""

        from .workspace_client import WorkspaceUnavailable

        digest = hashlib.sha256()
        received = 0
        try:
            async for chunk in self.response.aiter_bytes(1024 * 1024):
                if not chunk:
                    continue
                received += len(chunk)
                if received > self.size or received > MAX_DOCUMENT_ARTIFACT_BYTES:
                    raise WorkspaceUnavailable("document artifact exceeds its declared size")
                digest.update(chunk)
                yield chunk
            if received != self.size or digest.hexdigest() != self.sha256:
                raise WorkspaceUnavailable("document artifact integrity check failed")
        finally:
            await self.close()

    async def close(self) -> None:
        await self.response.aclose()
        await self.client.aclose()


async def document_profiles() -> dict:
    """Return the trusted profile manifest without leaking sidecar configuration."""

    from .workspace_client import WorkspaceUnavailable, _config, _log_boundary_failure

    enabled, base, timeout, key, _ = _config()
    if not enabled or not base:
        raise WorkspaceUnavailable("workspace sidecar is temporarily unavailable")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{base}/document-profiles", headers=headers)
    except Exception:
        _log_boundary_failure("document_profile_transport")
        raise WorkspaceUnavailable("workspace sidecar is temporarily unavailable") from None
    if response.status_code >= 400:
        _log_boundary_failure("document_profile_remote", status=response.status_code)
        raise WorkspaceUnavailable("workspace sidecar is temporarily unavailable")
    try:
        result = response.json()
    except ValueError:
        raise WorkspaceUnavailable("workspace sidecar returned an invalid response") from None
    if not isinstance(result, dict):
        raise WorkspaceUnavailable("workspace sidecar returned an invalid response")
    return result


async def create_document_project(
    ref: dict | None,
    *,
    path: str,
    profile_id: str,
    mode: str,
    locale: str | None,
    expected_revision: str,
    fence: int,
) -> dict | None:
    from .workspace_client import _call

    return await _call(
        ref,
        "documents",
        {
            "path": path,
            "profile_id": profile_id,
            "mode": mode,
            "locale": locale,
            "expected_revision": expected_revision,
            "coordination_fence": fence,
        },
    )


async def document_project_status(ref: dict | None, *, path: str) -> dict | None:
    from .workspace_client import _call

    return await _call(ref, "documents/status", {"path": path})


async def document_authoring_state(ref: dict | None, *, path: str) -> dict | None:
    from .workspace_client import _call

    return await _call(ref, "documents/authoring", {"path": path})


async def publish_document_source(
    ref: dict | None,
    *,
    path: str,
    files: dict[str, str],
    authoring_version: int,
    draft_digest: str,
    expected_revision: str,
    fence: int,
) -> dict | None:
    """Atomically replace only renderer-managed files in one document project."""

    from .workspace_client import _call

    return await _call(
        ref,
        "documents/source",
        {
            "path": path,
            "files": dict(files),
            "authoring_version": authoring_version,
            "draft_digest": draft_digest,
            "expected_revision": expected_revision,
            "coordination_fence": fence,
        },
        bounded_errors=frozenset(
            {"authoring_invalid", "source_too_large", "authoring_publish_failed"}
        ),
    )


async def apply_document_profile(
    ref: dict | None,
    *,
    path: str,
    target_path: str,
    profile_id: str,
    mode: str | None,
    locale: str | None,
    expected_revision: str,
    fence: int,
) -> dict | None:
    from .workspace_client import _call

    return await _call(
        ref,
        "documents/profile",
        {
            "path": path,
            "target_path": target_path,
            "profile_id": profile_id,
            "mode": mode,
            "locale": locale,
            "expected_revision": expected_revision,
            "coordination_fence": fence,
        },
    )


async def apply_document_vendor_overlay(
    ref: dict | None,
    *,
    path: str,
    source: dict,
    expected_revision: str,
    fence: int,
) -> dict | None:
    """Install one owner-checked Library ZIP without exposing its transport URL."""

    from .workspace_client import _call

    safe_source = {
        "url": str(source.get("url") or ""),
        **({"sha256": str(source.get("sha256") or "")} if source.get("sha256") else {}),
    }
    return await _call(
        ref,
        "documents/vendor",
        {
            "path": path,
            "source": safe_source,
            "expected_revision": expected_revision,
            "coordination_fence": fence,
        },
        bounded_errors=frozenset(
            {
                "vendor_archive_invalid",
                "vendor_manifest_invalid",
                "vendor_unsafe",
                "vendor_too_large",
                "vendor_collision",
                "vendor_source_unavailable",
                "vendor_integrity",
            }
        ),
    )


async def activate_document_vendor_profile(
    ref: dict | None,
    *,
    path: str,
    package_id: str,
    target_path: str,
    expected_revision: str,
    fence: int,
) -> dict | None:
    """Clone a project through an installed v2 overlay and its isolated probe."""

    from .workspace_client import _call

    return await _call(
        ref,
        "documents/vendor/activate",
        {
            "path": path,
            "package_id": package_id,
            "target_path": target_path,
            "expected_revision": expected_revision,
            "coordination_fence": fence,
        },
        bounded_errors=frozenset({"vendor_profile_invalid", "vendor_collision", "source_changed"}),
    )


async def start_document_build(
    ref: dict | None,
    *,
    path: str,
    expected_revision: str,
    fence: int,
    final: bool,
) -> dict | None:
    from .workspace_client import _call

    return await _call(
        ref,
        "documents/builds",
        {
            "path": path,
            "expected_revision": expected_revision,
            "coordination_fence": fence,
            "final": final,
        },
    )


async def document_build_status(ref: dict | None, *, build_id: str) -> dict | None:
    from .workspace_client import _call

    return await _call(ref, f"documents/builds/{build_id}", {})


async def cancel_document_build(ref: dict | None, *, build_id: str, fence: int) -> dict | None:
    from .workspace_client import _call

    return await _call(
        ref,
        f"documents/builds/{build_id}/cancel",
        {"coordination_fence": fence},
    )


def _safe_artifact_headers(response: httpx.Response) -> tuple[int, str, str, str]:
    try:
        size = int(response.headers.get("content-length") or 0)
    except ValueError:
        size = 0
    digest = str(response.headers.get("x-artifact-sha256") or "").lower()
    mime_type = str(response.headers.get("content-type") or "application/octet-stream").split(
        ";", 1
    )[0]
    disposition = str(response.headers.get("content-disposition") or "")
    match = re.search(r'filename="([^"\\/]+)"', disposition)
    return size, digest, mime_type, match.group(1) if match else "document.pdf"


def _valid_artifact_contract(size: int, digest: str, mime_type: str) -> bool:
    return (
        0 < size <= MAX_DOCUMENT_ARTIFACT_BYTES
        and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
        and mime_type in {"application/pdf", "application/zip"}
    )


async def stream_document_artifact(
    ref: dict | None,
    *,
    build_id: str,
    artifact_id: str,
) -> DocumentArtifactDownload:
    """Open a verified bounded stream; the caller owns it until iteration/close."""

    from .workspace_client import (
        WorkspaceGone,
        WorkspaceUnavailable,
        _config,
        _log_boundary_failure,
    )

    if not ref or not ref.get("workspace_id"):
        raise WorkspaceGone("workspace is unavailable")
    enabled, base, timeout, key, _ = _config()
    if not enabled or not base:
        raise WorkspaceUnavailable("workspace sidecar is temporarily unavailable")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    payload = {"user_id": ref.get("user_id", ""), "token": ref.get("token", "")}
    url = (
        f"{base}/workspaces/{ref['workspace_id']}/documents/builds/"
        f"{build_id}/artifacts/{artifact_id}"
    )
    client = httpx.AsyncClient(timeout=timeout)
    try:
        request = client.build_request("POST", url, json=payload, headers=headers)
        response = await client.send(request, stream=True)
    except Exception:
        await client.aclose()
        _log_boundary_failure("document_artifact_transport")
        raise WorkspaceUnavailable("workspace sidecar is temporarily unavailable") from None
    if response.status_code == 404:
        await response.aclose()
        await client.aclose()
        raise DocumentArtifactMissing("document artifact is unavailable")
    if response.status_code >= 400:
        status = response.status_code
        await response.aclose()
        await client.aclose()
        _log_boundary_failure("document_artifact_remote", status=status)
        raise WorkspaceUnavailable("document artifact is temporarily unavailable")
    size, digest, mime_type, filename = _safe_artifact_headers(response)
    if not _valid_artifact_contract(size, digest, mime_type):
        await response.aclose()
        await client.aclose()
        _log_boundary_failure("document_artifact_contract")
        raise WorkspaceUnavailable("document artifact contract is invalid")
    return DocumentArtifactDownload(client, response, filename, mime_type, size, digest)


__all__ = [
    "DocumentArtifactDownload",
    "DocumentArtifactMissing",
    "activate_document_vendor_profile",
    "apply_document_profile",
    "apply_document_vendor_overlay",
    "cancel_document_build",
    "create_document_project",
    "document_build_status",
    "document_authoring_state",
    "document_profiles",
    "document_project_status",
    "publish_document_source",
    "start_document_build",
    "stream_document_artifact",
]
