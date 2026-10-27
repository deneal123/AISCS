"""Web-router ledger receipts must survive the separate worker billing seam."""

from copy import deepcopy
from decimal import Decimal

import pytest

from service.services.billing.application import pricing_service
from service.services.billing.domain.pricing import ModelPrice
from service.services.chat.infrastructure.chat_worker.billing.charging import _charge_router_usage
from tests.test_billing_pricing import _cfg, _FakePricingRepo
from tests.test_charge_usage_anomaly import _patch_billing
from tests.test_helpers import FakeConnector, FakeDBSession


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 2])
async def test_router_charge_keeps_distinct_actual_model_receipts(monkeypatch, count):
    captured = _patch_billing(monkeypatch, credits=7)
    calls = [
        {
            "receipt_id": "router-call-" + str(index),
            "provider": "gigachat",
            "model": "GigaChat-2" if index == 0 else "GigaChat-2-Pro",
            "prompt": 2,
            "completion": 1,
            "total": 3,
            "kind": "route_model",
            **({"estimated": True} if index else {}),
        }
        for index in range(count)
    ]
    usage = {"prompt": 2 * count, "completion": count, "total": 3 * count, "calls": calls}
    original = deepcopy(usage)
    assert (
        await _charge_router_usage(
            pg_connector=FakeConnector(FakeDBSession()),
            redis_client=None,
            user_id="fixture-owner",
            session_data={"_router_usage": usage},
            thread_id="fixture-thread",
            job_id="fixture-job",
            config=object(),
        )
        == 7
    )
    charged = captured["charged"]
    assert charged["metadata"]["per_call"] == calls
    assert charged["metadata"]["provider"] == "gigachat"
    assert charged["metadata"]["model"] == ("GigaChat-2" if count == 1 else None)
    assert charged["tokens"] == 3 * count
    assert charged["idempotency_key"] == "fixture-job:router"
    assert usage == original


@pytest.mark.asyncio
async def test_legacy_router_aggregate_stays_supported_without_guessed_provider(monkeypatch):
    captured = _patch_billing(monkeypatch, credits=7)
    await _charge_router_usage(
        pg_connector=FakeConnector(FakeDBSession()),
        redis_client=None,
        user_id="fixture-owner",
        session_data={"_router_usage": {"prompt": 2, "completion": 1, "total": 3, "model": "m"}},
        thread_id="fixture-thread",
        job_id="fixture-job",
        config=object(),
    )
    assert captured["charged"]["metadata"]["per_call"] == [
        {"model": "m", "prompt": 2, "completion": 1}
    ]
    assert "provider" not in captured["charged"]["metadata"]


@pytest.mark.asyncio
async def test_router_prices_each_actual_model_without_answer_substitution_cap(monkeypatch):
    real_pricing = pricing_service.PricingService
    captured = _patch_billing(monkeypatch, credits=7)
    registry = _FakePricingRepo(
        {
            "GigaChat-2": ModelPrice(Decimal("2"), Decimal("2")),
            "GigaChat-2-Pro": ModelPrice(Decimal("7"), Decimal("7")),
        }
    )
    monkeypatch.setattr(
        pricing_service, "PricingService", lambda *_args: real_pricing(registry, _cfg())
    )
    calls = [
        {"model": model, "provider": "gigachat", "prompt": 1000, "completion": 0}
        for model in ("GigaChat-2", "GigaChat-2-Pro")
    ]
    charged = await _charge_router_usage(
        pg_connector=FakeConnector(FakeDBSession()),
        redis_client=None,
        user_id="fixture-owner",
        session_data={
            "_router_usage": {"prompt": 2000, "completion": 0, "total": 2000, "calls": calls}
        },
        thread_id="fixture-thread",
        job_id="fixture-job",
        config=object(),
    )
    # Two independent prices: (2 + 7) rub * 2.5 margin / 0.01 rub per credit.
    assert charged == 2250
    assert captured["charged"]["raw_cost_rub"] == 9
    assert captured["charged"]["metadata"]["per_call"] == calls
