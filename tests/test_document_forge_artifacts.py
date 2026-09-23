from __future__ import annotations

import hashlib
import uuid

import httpx
import pytest
from fastapi import HTTPException

from service.infrastructure import workspace_client
from service.infrastructure.agents_client.agent_file_bridge import persist_generated_artifacts
from service.services.chat.application import document_publication_service
from service.services.chat.infrastructure.chat_worker import artifacts
from service.services.chat.presentation.routers.chat_api.workspace_contracts import (
    DocumentVendorOverlayRequest,
)
from service.services.chat.presentation.routers.chat_api.workspace_document_routes import (
    _publication_descriptor,
    apply_document_vendor_overlay,
)


def _mock_stream_client(monkeypatch, content: bytes, digest: str) -> None:
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=content,
            headers={
                "content-type": "application/pdf",
                "content-length": str(len(content)),
                "content-disposition": 'attachment; filename="paper.pdf"',
                "x-artifact-sha256": digest,
            },
        )
    )
    monkeypatch.setattr(
        workspace_client.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    monkeypatch.setattr(
        workspace_client,
        "_config",
        lambda: (True, "http://workspace", 10.0, "service-key", None),
    )


def _mock_stream_status(monkeypatch, status: int) -> None:
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _request: httpx.Response(status))
    monkeypatch.setattr(
        workspace_client.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    monkeypatch.setattr(
        workspace_client,
        "_config",
        lambda: (True, "http://workspace", 10.0, "service-key", None),
    )


@pytest.mark.asyncio
async def test_document_artifact_transport_checks_digest(monkeypatch) -> None:
    content = b"%PDF-1.7\nsynthetic"
    _mock_stream_client(monkeypatch, content, hashlib.sha256(content).hexdigest())

    received = await workspace_client.stream_document_artifact(
        {"workspace_id": "opaque", "user_id": "owner", "token": "private"},
        build_id="build-1",
        artifact_id="artifact-1",
    )

    assert b"".join([chunk async for chunk in received.chunks()]) == content
    assert (received.filename, received.mime_type, received.size) == (
        "paper.pdf",
        "application/pdf",
        len(content),
    )


@pytest.mark.asyncio
async def test_document_artifact_transport_rejects_digest_mismatch(monkeypatch) -> None:
    content = b"tampered"
    _mock_stream_client(monkeypatch, content, "0" * 64)

    received = await workspace_client.stream_document_artifact(
        {"workspace_id": "opaque", "user_id": "owner", "token": "private"},
        build_id="build-1",
        artifact_id="artifact-1",
    )
    with pytest.raises(workspace_client.WorkspaceUnavailable):
        _ = [chunk async for chunk in received.chunks()]


@pytest.mark.asyncio
async def test_missing_document_artifact_does_not_claim_workspace_expired(monkeypatch) -> None:
    _mock_stream_status(monkeypatch, 404)

    with pytest.raises(workspace_client.DocumentArtifactMissing):
        await workspace_client.stream_document_artifact(
            {"workspace_id": "opaque", "user_id": "owner", "token": "private"},
            build_id="build-1",
            artifact_id="artifact-1",
        )


@pytest.mark.asyncio
async def test_final_document_artifacts_become_private_safe_outbox_descriptors() -> None:
    owner = uuid.uuid4()
    digest = hashlib.sha256(b"content").hexdigest()
    descriptors = [
        {
            "build_id": "build-1",
            "artifact_id": "pdf-1",
            "role": "pdf",
            "filename": "document.pdf",
            "mime_type": "application/pdf",
            "size": len(b"content"),
            "sha256": digest,
            "source_digest": "1" * 64,
        },
        {
            "build_id": "build-1",
            "artifact_id": "thumb-1",
            "role": "thumbnail",
            "filename": "preview.png",
            "mime_type": "image/png",
            "size": 1,
            "sha256": "2" * 64,
            "source_digest": "1" * 64,
        },
    ]
    metadata = {"document_artifacts": descriptors.copy()}

    await artifacts._persist_document_artifacts(object(), owner, metadata, {"workspace_id": "w"})

    assert "document_artifacts" not in metadata
    assert metadata["_document_publications"] == [
        {
            "build_id": "build-1",
            "artifact_id": "pdf-1",
            "role": "pdf",
            "source_digest": "1" * 64,
            "artifact_sha256": digest,
            "artifact_size": len(b"content"),
            "filename": "document.pdf",
            "mime_type": "application/pdf",
            "initial_status": "pending_delivery",
        }
    ]


@pytest.mark.asyncio
async def test_visual_pending_artifact_keeps_pending_audit_outbox_state() -> None:
    digest = hashlib.sha256(b"content").hexdigest()
    metadata = {
        "document_artifacts": [
            {
                "build_id": "build-2",
                "artifact_id": "pdf-2",
                "role": "pdf",
                "filename": "pending.pdf",
                "mime_type": "application/pdf",
                "size": 7,
                "sha256": digest,
                "source_digest": "2" * 64,
                "initial_status": "pending_audit",
            }
        ]
    }

    await artifacts._persist_document_artifacts(
        object(), uuid.uuid4(), metadata, {"workspace_id": "w"}
    )

    assert metadata["_document_publications"][0]["initial_status"] == "pending_audit"


@pytest.mark.asyncio
async def test_delivered_pdf_atomically_marks_assistant_document_completed() -> None:
    class Result:
        def mappings(self):
            return self

        def first(self):
            return {
                "id": 7,
                "metadata": {
                    "document_outcome": "deferred",
                    "document_failure_code": "delivery_deferred",
                    "execution_status": "deferred",
                    "document_project_saved": True,
                },
            }

    class Session:
        def __init__(self):
            self.values = []

        async def execute(self, _query, values):
            self.values.append(values)
            return Result()

    session = Session()
    await document_publication_service._attach_generated_file(
        session,
        {
            "assistant_message_id": 7,
            "role": "pdf",
            "filename": "document.pdf",
            "mime_type": "application/pdf",
        },
        uuid.uuid4(),
    )

    persisted = session.values[-1]["metadata"]
    assert '"document_outcome": "completed"' in persisted
    assert '"execution_status": "completed"' in persisted
    assert "delivery_deferred" not in persisted
    assert "document_project_saved" not in persisted


@pytest.mark.asyncio
async def test_plain_text_named_pdf_is_never_persisted_as_download() -> None:
    class _Files:
        async def save(self, **_kwargs):
            raise AssertionError("invalid PDF must not reach object storage")

    result = await persist_generated_artifacts(
        file_service=_Files(),
        user_id=uuid.uuid4(),
        metadata={
            "_pending_artifacts": [
                {
                    "filename": "test.pdf",
                    "file_b64": "0YLQtdGB0YI=",
                }
            ]
        },
        job_id="job-1",
    )

    assert result == (None, {})


def test_document_project_sources_never_enter_legacy_artifact_bridge() -> None:
    inventory = [
        {"path": "documents/document-1/main.tex", "size": 100},
        {"path": "documents/document-1/document.toml", "size": 50},
        {"path": "documents/document-1/artifacts/final.pdf", "size": 500},
        {"path": ".gpthub-document/jobs/build.json", "size": 50},
        {"path": "reports/result.csv", "size": 80},
    ]

    assert artifacts._collectable_workspace_inventory(inventory) == [
        {"path": "reports/result.csv", "size": 80}
    ]


def test_manual_publish_uses_canonical_descriptor_field_names() -> None:
    descriptor = _publication_descriptor(
        build_id="build-3",
        artifact_id="pdf-3",
        status={"source_digest": "3" * 64},
        artifact={
            "role": "pdf",
            "filename": "document.pdf",
            "mime_type": "application/pdf",
            "size": 12,
            "sha256": "4" * 64,
        },
    )

    assert descriptor["size"] == 12
    assert descriptor["sha256"] == "4" * 64
    assert "artifact_size" not in descriptor
    assert "artifact_sha256" not in descriptor


@pytest.mark.asyncio
async def test_vendor_overlay_uses_private_owned_library_source(monkeypatch) -> None:
    from service.services.chat.presentation.routers.chat_api import workspace_api

    file_id = uuid.uuid4()
    owner = uuid.uuid4()
    source = {
        "name": "publisher-kit.zip",
        "url": "https://internal.example/opaque",
        "sha256": "a" * 64,
    }
    calls: list[dict] = []

    class ChatService:
        async def ensure_thread_owner(self, thread_id: str, user_id: str) -> None:
            assert (thread_id, user_id) == ("thread-1", str(owner))

    class Files:
        async def resolve_chat_library_import(self, user_id, requested_id, *, expiry_sec: int):
            assert (user_id, requested_id, expiry_sec) == (owner, file_id, 120)
            return source

    class Store:
        async def preflight(self, _capability, *, mutation: str, path: str, fence: int):
            assert (mutation, path, fence) == ("write", "documents/paper", 7)
            return {"fence": fence}

        async def mark_stale(self, *, path: str, revision: str) -> None:
            assert (path, revision) == ("documents/paper", "rev-2")

        async def record_activity(self, action: str) -> None:
            assert action == "file_saved"

    async def read_binding(_redis, _thread_id):
        return {
            "workspace_id": "opaque-workspace",
            "token": "private-token",
            "expires_at": 4_000_000_000,
        }

    async def apply(ref, **kwargs):
        calls.append({"ref": ref, **kwargs})
        return {
            "outcome": "imported",
            "revision": "rev-2",
            "revision_changed": True,
            "overlay": {
                "package_id": "publisher-kit",
                "version": "1.0",
                "license": "LPPL-1.3c",
                "file_count": 3,
                "trusted": False,
                "digest": "b" * 64,
            },
        }

    monkeypatch.setattr(workspace_api.workspace_client, "read_binding", read_binding)
    monkeypatch.setattr(workspace_api.workspace_client, "apply_document_vendor_overlay", apply)
    monkeypatch.setattr(
        workspace_api,
        "_request_ui_capability",
        lambda _ref, _user_id, _session: "opaque-capability",
    )
    monkeypatch.setattr(workspace_api, "verify_capability", lambda _value: object())
    monkeypatch.setattr(workspace_api, "_collaboration", lambda _ref, _redis: Store())

    result = await apply_document_vendor_overlay(
        "thread-1",
        file_id,
        DocumentVendorOverlayRequest(path="documents/paper", expected_revision="rev-1", fence=7),
        type("Profile", (), {"user_id": owner})(),
        ChatService(),
        Files(),
        None,
        "browser-session-1234",
    )

    assert result == {
        "outcome": "imported",
        "revision": "rev-2",
        "overlay": {
            "package_id": "publisher-kit",
            "version": "1.0",
            "license": "LPPL-1.3c",
            "file_count": 3,
            "trusted": False,
        },
    }
    assert calls[0]["source"] is source
    assert calls[0]["ref"]["coordination_capability"] == "opaque-capability"
    assert "url" not in str(result).lower()

    async def rejected(*_args, **_kwargs):
        raise workspace_client.WorkspaceRequestRejected("vendor_collision", 409)

    monkeypatch.setattr(workspace_api.workspace_client, "apply_document_vendor_overlay", rejected)
    with pytest.raises(HTTPException) as caught:
        await apply_document_vendor_overlay(
            "thread-1",
            file_id,
            DocumentVendorOverlayRequest(
                path="documents/paper", expected_revision="rev-1", fence=7
            ),
            type("Profile", (), {"user_id": owner})(),
            ChatService(),
            Files(),
            None,
            "browser-session-1234",
        )
    assert (caught.value.status_code, caught.value.detail) == (409, "vendor_collision")


@pytest.mark.asyncio
async def test_vendor_overlay_preserves_only_allowlisted_sidecar_failure(monkeypatch) -> None:
    content = {"error": "vendor_collision", "detail": "private path must not escape"}
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _request: httpx.Response(409, json=content))
    monkeypatch.setattr(
        workspace_client.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    monkeypatch.setattr(
        workspace_client,
        "_config",
        lambda: (True, "http://workspace", 10.0, "service-key", None),
    )

    with pytest.raises(workspace_client.WorkspaceRequestRejected) as caught:
        await workspace_client.apply_document_vendor_overlay(
            {
                "workspace_id": "opaque",
                "user_id": "owner",
                "token": "private",
                "coordination_capability": "private-capability",
            },
            path="documents/paper",
            source={"url": "https://private.example/file.zip", "sha256": "a" * 64},
            expected_revision="rev-1",
            fence=3,
        )

    assert (caught.value.code, caught.value.status_code) == ("vendor_collision", 409)
    assert "private path" not in str(caught.value)
