from __future__ import annotations

import uuid

import pytest

from service.infrastructure.agents_client import document_audit
from service.models.db.db_models import DocumentAuditAttempt
from service.services.chat.application import document_publication_service


@pytest.mark.asyncio
async def test_document_audit_keeps_the_ledger_envelope(monkeypatch) -> None:
    usage = {
        "prompt": 120,
        "completion": 4,
        "total": 124,
        "model": "vision-model",
        "calls": [{"model": "vision-model", "prompt": 120, "completion": 4}],
    }

    async def request_json(self, *_args, **_kwargs):
        return {"status": "passed", "passed": True, "retryable": False, "usage": usage}

    monkeypatch.setattr(document_audit.SidecarClient, "request_json", request_json)

    result = await document_audit.audit_document(
        object(), workspace_ref={"workspace_id": "opaque"}, build_id="build-123"
    )

    assert result["usage"] == usage


@pytest.mark.asyncio
async def test_deferred_visual_audit_uses_one_idempotent_charge_key(monkeypatch) -> None:
    calls: list[dict] = []

    async def charge_usage(**kwargs):
        calls.append(kwargs)
        return 7

    from service.services.chat.infrastructure.chat_worker import charging

    monkeypatch.setattr(charging, "_charge_usage", charge_usage)
    row = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "thread_id": "thread-1",
        "billing_job_id": "job-1",
        "build_id": "build-1",
    }
    usage = {
        "prompt": 20,
        "completion": 2,
        "total": 22,
        "model": "vision-model",
        "calls": [
            {
                "model": "vision-model",
                "provider": "openai",
                "prompt": 20,
                "completion": 2,
                "kind": "document_visual_audit",
            }
        ],
    }

    await document_publication_service._charge_visual_audit(
        config=object(), pg_connector=object(), redis=object(), row=row, usage=usage
    )

    assert len(calls) == 1
    assert calls[0]["job_id"] == "job-1:document-audit:build-1"
    assert calls[0]["execution_result"]["per_call_usage"] == usage["calls"]


def test_document_audit_usage_is_bounded_and_recomputed() -> None:
    result = document_audit._bounded_usage(
        {
            "prompt": 999999,
            "completion": 999999,
            "calls": [
                {
                    "model": "vision-model",
                    "provider": "openai",
                    "kind": "document_visual_audit",
                    "prompt": 120,
                    "completion": 4,
                },
                "invalid",
            ],
        }
    )

    assert result["total"] == 124
    assert result["calls"] == [
        {
            "model": "vision-model",
            "provider": "openai",
            "kind": "document_visual_audit",
            "prompt": 120,
            "completion": 4,
        }
    ]


def test_only_one_unsettled_audit_attempt_is_allowed_per_publication() -> None:
    indexes = {index.name: index for index in DocumentAuditAttempt.__table__.indexes}
    index = indexes["uq_document_audit_attempt_open"]

    assert index.unique is True
    assert [column.name for column in index.columns] == ["publication_job_id"]
    assert "charge_pending" in str(index.dialect_options["postgresql"]["where"])


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_charge_pending_attempt_resumes_without_second_visual_call(monkeypatch) -> None:
    attempt_id = uuid.uuid4()
    usage = {
        "prompt": 30,
        "completion": 3,
        "total": 33,
        "model": "vision-model",
        "calls": [{"model": "vision-model", "prompt": 30, "completion": 3}],
    }
    states = iter(({"state": "visual_pending"}, {"state": "ready"}))
    audit_calls = 0
    charge_calls: list[uuid.UUID | None] = []
    settled: list[tuple[uuid.UUID, str]] = []

    async def status(*_args, **_kwargs):
        return next(states)

    async def begin(*_args, **_kwargs):
        return {
            "id": attempt_id,
            "state": "charge_pending",
            "usage_envelope": usage,
            "failure_code": None,
        }

    async def audit(*_args, **_kwargs):
        nonlocal audit_calls
        audit_calls += 1
        return {}

    async def charge(**kwargs):
        charge_calls.append(kwargs.get("attempt_id"))
        return "charge-1"

    async def settle(_session, *, attempt_id, charge_id):
        settled.append((attempt_id, charge_id))
        return True

    monkeypatch.setattr(document_publication_service, "document_build_status", status)
    monkeypatch.setattr(document_publication_service.document_audit_attempts, "begin", begin)
    monkeypatch.setattr(document_publication_service, "audit_document", audit)
    monkeypatch.setattr(document_publication_service, "_charge_visual_audit", charge)
    monkeypatch.setattr(document_publication_service.document_audit_attempts, "settle", settle)
    session = _Session()

    result = await document_publication_service._ensure_audited_durable(
        config=object(),
        pg_connector=object(),
        redis=object(),
        session=session,
        ref={"workspace_id": "opaque"},
        row={"build_id": "build-1"},
    )

    assert result == "ready"
    assert audit_calls == 0
    assert charge_calls == [attempt_id]
    assert settled == [(attempt_id, "charge-1")]
    assert session.commits == 2


@pytest.mark.asyncio
async def test_failed_visual_result_is_charged_before_terminal_decision(monkeypatch) -> None:
    attempt_id = uuid.uuid4()
    usage = {
        "prompt": 40,
        "completion": 4,
        "total": 44,
        "model": "vision-model",
        "calls": [{"model": "vision-model", "prompt": 40, "completion": 4}],
    }
    order: list[str] = []

    async def status(*_args, **_kwargs):
        return {"state": "visual_pending"}

    async def begin(*_args, **_kwargs):
        return {"id": attempt_id, "state": "started"}

    async def audit(*_args, **_kwargs):
        order.append("audit")
        return {"passed": False, "retryable": False, "usage": usage}

    async def record(*_args, **kwargs):
        order.append("record")
        assert kwargs["usage"] == usage
        assert kwargs["failure_code"] == "audit_failed"
        return True

    async def charge(**kwargs):
        order.append("charge")
        assert kwargs["usage"] == usage
        return "charge-2"

    async def settle(*_args, **kwargs):
        order.append("settle")
        assert kwargs["charge_id"] == "charge-2"
        return True

    monkeypatch.setattr(document_publication_service, "document_build_status", status)
    monkeypatch.setattr(document_publication_service.document_audit_attempts, "begin", begin)
    monkeypatch.setattr(document_publication_service, "audit_document", audit)
    monkeypatch.setattr(
        document_publication_service.document_audit_attempts, "record_result", record
    )
    monkeypatch.setattr(document_publication_service, "_charge_visual_audit", charge)
    monkeypatch.setattr(document_publication_service.document_audit_attempts, "settle", settle)

    result = await document_publication_service._ensure_audited_durable(
        config=object(),
        pg_connector=object(),
        redis=object(),
        session=_Session(),
        ref={"workspace_id": "opaque"},
        row={"build_id": "build-1"},
    )

    assert result == "artifact_invalid"
    assert order == ["audit", "record", "charge", "settle"]
