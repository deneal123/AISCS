"""Reusing an owned upload intent must not schedule another paid index pass."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from service.composition.state import (
    get_billing_service,
    get_chat_application_service,
    get_optional_redis_client,
)
from service.services.chat.application.use_cases.upload_file_use_case import UploadFileUseCase
from service.services.chat.presentation.http import upload_api
from service.shared.security.auth_checker import check_auth


@pytest.mark.asyncio
@pytest.mark.parametrize("reused", [False, True])
async def test_owned_source_reuse_is_private_use_case_state(reused):
    file_id, owner = uuid4(), uuid4()
    files = SimpleNamespace(
        save=AsyncMock(
            return_value=SimpleNamespace(
                file_id=file_id,
                file_url="internal://private",
                file_key="private-key",
                reused=reused,
            )
        )
    )
    use_case = UploadFileUseCase(media_analysis_port=object(), file_service=files)
    result = await use_case.execute(
        filename="fixture.txt",
        content_type="text/plain",
        content_bytes=b"synthetic",
        thread_id="",
        user_id=str(owner),
        upload_intent_id=str(uuid4()),
    )
    assert result["_library_reused"] is reused
    assert result["file_id"] == str(file_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("reused", [False, True])
async def test_route_schedules_index_only_for_new_owned_source(reused, monkeypatch):
    owner, file_id = uuid4(), uuid4()
    result = {
        "filename": "fixture.txt",
        "file_type": "text",
        "size": 9,
        "extracted_text": "synthetic",
        "thread_id": "",
        "file_id": str(file_id),
        "content_sha256": "a" * 64,
        "mime_type": "text/plain",
        "file_url": "internal://private",
        "file_key": "private-key",
        "temp_file": True,
        "_library_reused": reused,
    }
    execute = AsyncMock(return_value=result)
    monkeypatch.setattr(
        upload_api, "get_upload_use_case", lambda _: SimpleNamespace(execute=execute)
    )
    scheduled = Mock()
    monkeypatch.setattr(upload_api, "_schedule_graph_indexing", scheduled)
    monkeypatch.setattr(upload_api, "_affordable_transcription_sec", AsyncMock(return_value=None))
    billing = SimpleNamespace(has_sufficient_credits=AsyncMock(return_value=True))
    app = FastAPI()
    app.include_router(upload_api.upload_router, prefix="/api/chats")
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=owner)
    app.dependency_overrides[get_billing_service] = lambda: billing
    app.dependency_overrides[get_chat_application_service] = lambda: SimpleNamespace(
        file_service=object()
    )
    app.dependency_overrides[get_optional_redis_client] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.post(
            "/api/chats/upload",
            files={"file": ("fixture.txt", b"synthetic", "text/plain")},
        )
    assert response.status_code == 200
    assert "_library_reused" not in response.json()
    assert scheduled.call_count == (0 if reused else 1)
    if not reused:
        assert "_library_reused" not in scheduled.call_args.args[0]


@pytest.mark.asyncio
async def test_graph_charge_uses_owned_file_idempotency_not_filename(monkeypatch):
    from service.infrastructure import graphify
    from service.infrastructure.agents_client import sidecar_vector
    from service.settings import config

    scheduled = []
    monkeypatch.setattr(
        upload_api,
        "asyncio",
        SimpleNamespace(
            get_running_loop=lambda: SimpleNamespace(create_task=scheduled.append),
            gather=asyncio.gather,
        ),
    )
    monkeypatch.setattr(upload_api.runtime_settings, "get_agents", lambda *_: True)
    monkeypatch.setattr(graphify, "user_graph_id", lambda _: "fixture-graph")
    monkeypatch.setattr(graphify, "text_to_targz", lambda *_: b"synthetic")
    monkeypatch.setattr(
        graphify,
        "GraphifyClient",
        lambda: SimpleNamespace(
            enabled=True,
            build=AsyncMock(return_value={"nodes": 1, "edges": 0}),
        ),
    )
    monkeypatch.setattr(sidecar_vector, "index_document_best_effort", AsyncMock(return_value=0))
    monkeypatch.setattr(config.agents, "graph_index_price_rub_per_doc", 1.0)
    billing = SimpleNamespace(charge=AsyncMock())
    owner, file_id = str(uuid4()), uuid4()
    upload_api._schedule_graph_indexing(
        {
            "file_id": str(file_id),
            "filename": "private-name.txt",
            "file_type": "text",
            "extracted_text": "synthetic",
        },
        owner,
        billing,
    )
    assert len(scheduled) == 1
    await scheduled[0]
    billing.charge.assert_awaited_once()
    assert billing.charge.await_args.kwargs["idempotency_key"] == f"graph-index:{file_id.hex}"


@pytest.mark.parametrize("file_id", [None, "", "not-a-file-id", {"private": "marker"}])
def test_unowned_index_identity_does_not_schedule_or_charge(file_id, monkeypatch):
    from service.infrastructure import graphify

    monkeypatch.setattr(upload_api.runtime_settings, "get_agents", lambda *_: True)
    monkeypatch.setattr(graphify, "user_graph_id", lambda _: "fixture-graph")
    client = Mock(side_effect=AssertionError("unowned source must not construct a client"))
    monkeypatch.setattr(graphify, "GraphifyClient", client)
    upload_api._schedule_graph_indexing(
        {
            "file_id": file_id,
            "filename": "fixture.txt",
            "file_type": "text",
            "extracted_text": "synthetic",
        },
        str(uuid4()),
        SimpleNamespace(charge=AsyncMock()),
    )
    client.assert_not_called()
