"""Upload integration diagnostics are bounded even when upstream errors are not."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.application.use_cases import upload_file_use_case
from service.services.chat.presentation.http import upload_api

MARKER = "PRIVATE_UPLOAD_INTEGRATION_BODY"
OWNER = "PRIVATE_UPLOAD_OWNER"


@pytest.fixture
def capture(monkeypatch, caplog):
    monkeypatch.setattr(upload_api.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(upload_api.logger, "propagate", False)
    caplog.set_level(logging.DEBUG, logger=upload_api.logger.name)
    monkeypatch.setattr(upload_file_use_case.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(upload_file_use_case.logger, "propagate", False)
    caplog.set_level(logging.DEBUG, logger=upload_file_use_case.logger.name)
    return caplog


def assert_private(capture):
    assert MARKER not in capture.text
    assert OWNER not in capture.text
    assert capture.records
    assert all(record.exc_info is None for record in capture.records)
    assert all(getattr(record, "component", None) == "chat_upload" for record in capture.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["claim", "release", "balance", "transcription"])
async def test_failure_branches_do_not_log_exception_bodies(operation, capture):
    redis = SimpleNamespace(
        set=AsyncMock(side_effect=OSError(MARKER)),
        delete=AsyncMock(side_effect=OSError(MARKER)),
    )
    billing = SimpleNamespace(
        get_balance=AsyncMock(side_effect=OSError(MARKER)),
        charge=AsyncMock(side_effect=OSError(MARKER)),
    )
    if operation == "claim":
        assert await upload_api._claim_transcription_charge(redis, OWNER, "digest") is True
    elif operation == "release":
        await upload_api._release_transcription_charge(redis, OWNER, "digest")
    elif operation == "balance":
        assert await upload_api._affordable_transcription_sec(billing, OWNER, None) == float("inf")
    else:
        redis.set.side_effect = None
        redis.set.return_value = True
        await upload_api._charge_transcription(
            billing,
            redis,
            OWNER,
            "digest",
            {"engine": "local", "duration_sec": 60, "model": "base"},
        )
        billing.charge.assert_awaited_once()
        redis.delete.assert_awaited_once()
    assert_private(capture)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["archive", "build"])
async def test_repository_fallback_logs_are_private(stage, monkeypatch, capture):
    from service.infrastructure import graphify

    def convert(_):
        if stage == "archive":
            raise OSError(MARKER)
        return b"fixture"

    monkeypatch.setattr(graphify, "zip_to_targz", convert)
    monkeypatch.setattr(graphify, "archive_listing", lambda _: "fixture listing")
    use_case = upload_file_use_case.UploadFileUseCase(
        media_analysis_port=object(),
        file_service=object(),
        graph_client=SimpleNamespace(enabled=True, build=AsyncMock(side_effect=OSError(MARKER))),
    )
    result = await use_case._analyze_repository(OWNER + ".zip", b"fixture")
    assert result == ("" if stage == "archive" else "fixture listing")
    assert_private(capture)
    assert all(getattr(record, "failure_code", None) == "unavailable" for record in capture.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["image", "transcription"])
async def test_dedup_logs_do_not_include_owner(kind, capture):
    redis = SimpleNamespace(set=AsyncMock(return_value=False))
    billing = SimpleNamespace(charge=AsyncMock())
    if kind == "image":
        await upload_api._charge_image_usage(billing, redis, OWNER, "digest", {"total": 20})
    else:
        await upload_api._charge_transcription(
            billing,
            redis,
            OWNER,
            "digest",
            {"engine": "provider", "duration_sec": 60, "model": "base"},
        )
    billing.charge.assert_not_awaited()
    assert_private(capture)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["build", "charge"])
async def test_graph_failure_logs_neither_filename_nor_exception(stage, monkeypatch, capture):
    from service.infrastructure import graphify
    from service.infrastructure.agents_client import sidecar_vector

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
    monkeypatch.setattr(graphify, "user_graph_id", lambda _: "private-graph")
    monkeypatch.setattr(graphify, "text_to_targz", lambda *_: b"fixture")
    monkeypatch.setattr(
        graphify,
        "GraphifyClient",
        lambda: SimpleNamespace(
            enabled=True,
            build=AsyncMock(
                return_value={"nodes": 1, "edges": 0},
                side_effect=OSError(MARKER) if stage == "build" else None,
            ),
        ),
    )
    from service.settings import config

    monkeypatch.setattr(config.agents, "graph_index_price_rub_per_doc", 1.0)
    billing = SimpleNamespace(charge=AsyncMock(side_effect=OSError(MARKER)))
    monkeypatch.setattr(sidecar_vector, "index_document_best_effort", AsyncMock(return_value=0))
    upload_api._schedule_graph_indexing(
        {
            "file_id": "b9d4d44e-e3e6-47bd-a3c7-e43201186e91",
            "filename": OWNER + ".md",
            "file_type": "text",
            "extracted_text": "fixture",
        },
        OWNER,
        billing,
    )
    assert len(scheduled) == 1
    await scheduled[0]
    assert billing.charge.await_count == (1 if stage == "charge" else 0)
    assert_private(capture)


@pytest.mark.asyncio
async def test_image_charge_failure_is_bounded_and_releases_marker(monkeypatch, capture):
    from service.services.chat.infrastructure.chat_worker import factory
    from service.services.chat.infrastructure.chat_worker.billing import charging

    charge = AsyncMock(side_effect=OSError(MARKER))
    monkeypatch.setattr(charging, "_charge_usage", charge)
    monkeypatch.setattr(
        factory.ChatWorkerDependencyFactory, "create_pg_connector", lambda *_: object()
    )
    redis = SimpleNamespace(set=AsyncMock(return_value=True), delete=AsyncMock())
    await upload_api._charge_image_usage(
        object(),
        redis,
        OWNER,
        "digest",
        {"total": 20, "model": "fixture", "prompt": 12, "completion": 8},
    )
    charge.assert_awaited_once()
    redis.delete.assert_awaited_once()
    assert_private(capture)


@pytest.mark.asyncio
async def test_repository_binding_failure_preserves_upload_and_redacts_error(monkeypatch, capture):
    from io import BytesIO

    from fastapi import UploadFile

    from service.models.auth_models import AuthProfile
    from service.models.key_value import UserTypes
    from service.services.chat.infrastructure.chat_worker.context import attachment_evidence

    owner, thread, file_id = uuid4(), uuid4(), uuid4()
    result = {
        "filename": "fixture.zip",
        "file_type": "repository",
        "size": 7,
        "extracted_text": "fixture",
        "thread_id": str(thread),
        "file_id": str(file_id),
        "content_sha256": "a" * 64,
        "mime_type": "application/zip",
        "file_url": "owned",
        "file_key": "owned",
        "temp_file": False,
        "repo_graph_id": "private-graph",
    }
    monkeypatch.setattr(
        upload_api,
        "get_upload_use_case",
        lambda _: SimpleNamespace(execute=AsyncMock(return_value=result)),
    )
    monkeypatch.setattr(upload_api, "_affordable_transcription_sec", AsyncMock(return_value=None))
    monkeypatch.setattr(upload_api, "_schedule_graph_indexing", lambda *_: None)
    monkeypatch.setattr(attachment_evidence, "cache_owner_attachment_evidence", AsyncMock())
    redis = SimpleNamespace(lpush=AsyncMock(side_effect=OSError(MARKER)))
    response = await upload_api.upload_file_to_chat(
        profile=AuthProfile(user_id=owner, fingerprint=None, type=UserTypes.REGISTERED),
        file=UploadFile(file=BytesIO(b"fixture"), filename="fixture.zip"),
        thread_id=str(thread),
        transcription_mode="local",
        transcription_model="",
        chat_application_service=SimpleNamespace(
            file_service=object(), ensure_thread_owner=AsyncMock()
        ),
        billing_service=SimpleNamespace(has_sufficient_credits=AsyncMock(return_value=True)),
        redis_client=redis,
        upload_intent_id=None,
    )
    assert response.file_id == str(file_id)
    redis.lpush.assert_awaited_once()
    assert_private(capture)
