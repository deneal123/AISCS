"""Replay is not another provider call; distinct receipt identities remain distinct."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from service.infrastructure.agents_client.document_audit import client as document_audit


def _call(identity="accepted-call", **changes):
    return {
        "receipt_id": identity,
        "model": "GigaChat-2-Max",
        "provider": "gigachat",
        "kind": "document_visual_audit",
        "prompt": 12,
        "completion": 3,
        **changes,
    }


def test_exact_receipt_replay_does_not_double_tokens_or_mutate_input():
    raw = {"calls": [_call(), _call(), _call("another-call")]}
    original = deepcopy(raw)
    result = document_audit._bounded_usage(raw)
    assert result["total"] == 30
    assert [c["receipt_id"] for c in result["calls"]] == ["accepted-call", "another-call"]
    assert raw == original


@pytest.mark.parametrize("reverse", [False, True])
def test_exact_usage_refines_one_estimated_receipt_without_order_dependence(reverse):
    calls = [_call(prompt=20, estimated=True), _call()]
    result = document_audit._bounded_usage({"calls": calls[::-1] if reverse else calls})
    assert result["total"] == 15
    assert len(result["calls"]) == 1
    assert not result["calls"][0].get("estimated")


def test_legacy_calls_without_identity_are_not_coalesced_by_equal_content():
    calls = [_call(), _call()]
    for call in calls:
        call.pop("receipt_id")
    assert document_audit._bounded_usage({"calls": calls})["total"] == 30


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [{"model": "other-model"}, {"provider": "openai"}, {"kind": "chat"}, {"prompt": 99}],
)
async def test_conflicting_receipt_prevents_certification_but_preserves_known_usage(
    monkeypatch, changes
):
    monkeypatch.setattr(document_audit.provider_policy, "disabled_providers", lambda: ())
    monkeypatch.setattr(
        document_audit.provider_policy, "blocked_providers", AsyncMock(return_value=())
    )
    monkeypatch.setattr(
        document_audit.SidecarClient,
        "request_json",
        AsyncMock(
            return_value={
                "status": "passed",
                "passed": True,
                "retryable": False,
                "usage": {"calls": [_call(), _call(**changes)]},
            }
        ),
    )
    result = await document_audit.audit_document(object(), workspace_ref={}, build_id="fixture")
    assert result["status"] == "protocol"
    assert result["passed"] is False
    assert result["usage"]["total"] == 15
    assert len(result["usage"]["calls"]) == 1
