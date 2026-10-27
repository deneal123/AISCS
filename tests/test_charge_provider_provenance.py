"""Billing provider attribution comes from receipts, never from model ownership."""

import pytest

from service.services.chat.infrastructure.chat_worker.billing.charging import _charge_usage
from service.services.chat.infrastructure.chat_worker.billing.usage import (
    provenance as usage_provenance,
)
from tests.test_charge_usage_anomaly import _patch_billing
from tests.test_helpers import FakeConnector, FakeDBSession


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "receipts,expected",
    [
        ([{"provider": "gigachat", "model": "GigaChat-2"}], "gigachat"),
        ([{"provider": "routerai", "model": "openai/gpt-4o"}], "routerai"),
        ([{"provider": "openrouter", "model": "openai/gpt-4o"}], "openrouter"),
        (
            [
                {"provider": "gigachat", "model": "GigaChat-2"},
                {"provider": "routerai", "model": "openai/gpt-4o"},
            ],
            None,
        ),
        ([{"model": "openai/gpt-4o"}], None),
    ],
)
async def test_charge_provider_metadata_preserves_receipt_provenance(
    monkeypatch, receipts, expected
):
    captured = _patch_billing(monkeypatch, credits=7)
    calls = [{**receipt, "prompt": 2, "completion": 1} for receipt in receipts]
    charged = await _charge_usage(
        pg_connector=FakeConnector(FakeDBSession()),
        redis_client=None,
        user_id="fixture-owner",
        execution_result={
            "total_tokens": 3 * len(calls),
            "reply_chars_count": 10,
            "per_call_usage": calls,
        },
        thread_id="fixture-thread",
        job_id="fixture-job",
        resolved_model=calls[-1]["model"],
        config=object(),
    )
    metadata = captured["charged"]["metadata"]
    assert metadata.get("provider") == expected
    assert metadata["per_call"] == calls
    assert charged == 7


@pytest.mark.parametrize("provider", [None, 123, {"private": "sentinel"}, "private-sentinel"])
def test_unconfirmed_provider_is_not_logged_or_guessed(monkeypatch, caplog, provider):
    monkeypatch.setattr(usage_provenance.logger, "disabled", False)
    monkeypatch.setattr(usage_provenance.logger, "propagate", False)
    monkeypatch.setattr(usage_provenance.logger, "handlers", [caplog.handler])
    receipt = {"provider": provider, "model": "private-sentinel", "prompt": 2}
    assert usage_provenance.aggregate_provider([receipt]) is None
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.component == "billing"
    assert record.failure_code == "usage_provenance"
    assert "sentinel" not in str(record.__dict__)


def test_empty_receipts_have_no_aggregate_provider():
    assert usage_provenance.aggregate_provider([]) is None
