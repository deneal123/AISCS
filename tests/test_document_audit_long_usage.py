"""All page-batch receipts survive the audit-to-durable-settlement boundary."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.infrastructure.agents_client.document_audit import client as document_audit
from service.services.chat.application.documents.publication import (
    service as document_publication_service,
)
from service.services.chat.persistence.documents.audit import attempts as document_audit_attempts


def _page_batch_count():
    source = Path(__file__).parents[2] / "agents/service/domain/documents/visual_audit.py"
    values = {}
    for node in ast.parse(source.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"MAX_PAGES", "PAGES_PER_CALL"}:
                    values[target.id] = node.value.value
    return (values["MAX_PAGES"] + values["PAGES_PER_CALL"] - 1) // values["PAGES_PER_CALL"]


def _calls():
    return [
        {
            "receipt_id": f"synthetic-audit-{index}",
            "model": "GigaChat-2-Max",
            "provider": "gigachat",
            "kind": "document_visual_audit",
            "prompt": 10 + index,
            "completion": 2,
            "estimated": index % 2 == 1,
        }
        for index in range(_page_batch_count())
    ]


def test_full_page_corpus_keeps_every_receipt_and_exact_estimated_usage():
    calls = _calls()
    usage = document_audit._bounded_usage({"calls": calls})
    assert len(usage["calls"]) == len(calls)
    assert [item["receipt_id"] for item in usage["calls"]] == [item["receipt_id"] for item in calls]
    assert usage["total"] == sum(item["prompt"] + item["completion"] for item in calls)
    assert [item.get("estimated", False) for item in usage["calls"]] == [
        item["estimated"] for item in calls
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,retryable", [("failed", False), ("vision_unavailable", True)])
async def test_failed_long_audit_retains_usage_through_record_and_charge(
    monkeypatch, status, retryable
):
    calls = _calls()
    monkeypatch.setattr(document_audit.provider_policy, "disabled_providers", lambda: ())
    monkeypatch.setattr(
        document_audit.provider_policy, "blocked_providers", AsyncMock(return_value=())
    )
    monkeypatch.setattr(
        document_audit.SidecarClient,
        "request_json",
        AsyncMock(
            return_value={
                "status": status,
                "passed": False,
                "retryable": retryable,
                "usage": {"calls": calls * 2},
            }
        ),
    )
    result = await document_audit.audit_document(
        object(), workspace_ref={}, build_id="fixture-build"
    )
    selected = SimpleNamespace(
        mappings=lambda: SimpleNamespace(first=lambda: {"state": "started", "usage_envelope": {}})
    )
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[selected, SimpleNamespace(rowcount=1)])
    )
    attempt = uuid4()
    await document_audit_attempts.record_result(
        session,
        attempt_id=attempt,
        usage=result["usage"],
        failure_code="audit_unavailable",
    )
    recorded = json.loads(session.execute.call_args.args[1]["usage"])
    assert len(recorded["calls"]) == len(calls)
    charged = AsyncMock(return_value="synthetic-charge")
    monkeypatch.setattr(
        "service.services.chat.infrastructure.chat_worker.billing.charging._charge_usage",
        charged,
    )
    await document_publication_service._charge_visual_audit(
        config=object(),
        pg_connector=object(),
        redis=object(),
        row={
            "user_id": "fixture-owner",
            "thread_id": "fixture-thread",
            "billing_job_id": "fixture-job",
        },
        usage=recorded,
        attempt_id=attempt,
    )
    charged.assert_awaited_once()
    envelope = charged.call_args.kwargs
    assert envelope["job_id"] == f"fixture-job:document-audit:{attempt}"
    assert envelope["execution_result"]["per_call_usage"] == recorded["calls"]
    assert envelope["execution_result"]["total_tokens"] == sum(
        call["prompt"] + call["completion"] for call in calls
    )
