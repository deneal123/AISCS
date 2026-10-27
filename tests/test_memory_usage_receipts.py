"""The gateway receipt survives memory extraction and its separate charge."""

from copy import deepcopy

import pytest

from service.services.analytics.application.memory.service import MemoryService
from service.services.chat.infrastructure.chat_worker.billing.charging import _charge_memory_usage
from tests.test_charge_usage_anomaly import _patch_billing
from tests.test_helpers import FakeConnector, FakeDBSession

CALL = {
    "receipt_id": "memory-call",
    "provider": "gigachat",
    "model": "GigaChat-2",
    "prompt": 2,
    "completion": 1,
    "total": 3,
}


def test_memory_accumulator_preserves_actual_receipt_and_replay():
    usage = {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3, "calls": [CALL]}
    original = deepcopy(usage)
    out = {}
    MemoryService._accumulate_usage(out, usage)
    MemoryService._accumulate_usage(out, usage)
    assert out["calls"] == [CALL]
    assert out["model"] == "GigaChat-2"
    assert (out["prompt"], out["completion"], out["total"]) == (2, 1, 3)
    assert usage == original


def test_legacy_usage_is_not_lost_when_a_receipt_arrives_later():
    out = {}
    MemoryService._accumulate_usage(
        out, {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}
    )
    MemoryService._accumulate_usage(out, {"calls": [CALL]})
    assert len(out["calls"]) == 2
    assert out["calls"][1] == CALL
    assert (out["prompt"], out["completion"], out["total"]) == (6, 2, 8)
    assert "provider" not in out["calls"][0]


def test_receipt_conflict_does_not_replace_accepted_usage(monkeypatch, caplog):
    from service.services.analytics.application.memory import service as memory_service

    monkeypatch.setattr(memory_service.logger, "disabled", False)
    monkeypatch.setattr(memory_service.logger, "propagate", False)
    monkeypatch.setattr(memory_service.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(memory_service.logger, "level", 10)
    out = {}
    MemoryService._accumulate_usage(out, {"calls": [CALL]})
    original = deepcopy(out)
    MemoryService._accumulate_usage(
        out, {"calls": [{**CALL, "completion": 7, "model": "private-marker"}]}
    )
    assert out == original
    assert len(caplog.records) == 1
    assert caplog.records[0].failure_code == "usage_receipt"
    assert caplog.records[0].exc_info is None
    assert "private-marker" not in str(caplog.records[0].__dict__)


@pytest.mark.asyncio
async def test_memory_worker_charges_exact_receipt(monkeypatch):
    captured = _patch_billing(monkeypatch, credits=7)
    charged = await _charge_memory_usage(
        pg_connector=FakeConnector(FakeDBSession()),
        redis_client=None,
        user_id="fixture-owner",
        mem_usage={"prompt": 2, "completion": 1, "total": 3, "calls": [CALL]},
        thread_id="fixture-thread",
        job_id="fixture-job",
        config=object(),
    )
    assert charged == 7
    assert captured["charged"]["metadata"]["per_call"] == [CALL]
    assert captured["charged"]["metadata"]["provider"] == "gigachat"
    assert captured["charged"]["idempotency_key"] == "fixture-job:memory"
