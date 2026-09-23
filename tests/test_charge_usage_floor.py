"""_charge_usage НЕ должен отдавать сгенерированный ответ бесплатно.

Регрессия (fail-open по деньгам): раньше total_tokens<=0 (провайдер не вернул
usage) или падение тарификации давали credits=0 → полностью выданный ответ LLM за 0.
Теперь при отданном ответе списывается зарезервированная оценка (floor), а событие
помечается billing_fallback для сверки.
"""

import pytest

import service.services.billing.application.billing_service as bs_mod
import service.services.billing.application.pricing_service as ps_mod
import service.services.chat.infrastructure.chat_worker.charging as charging
from tests.test_helpers import FakeConnector, FakeDBSession


def _patch_billing(monkeypatch, *, pricing_raises: bool):
    captured: dict = {"charged": None, "released": False}

    class _FakeBilling:
        def __init__(self, *a, **k):
            pass

        async def charge(self, user_id, **kw):
            captured["charged"] = {"user_id": user_id, **kw}
            return {"from_subscription": kw.get("credits", 0), "from_topup": 0}

        async def release_reservation(self, *a, **k):
            captured["released"] = True

    class _FakePricing:
        def __init__(self, *a, **k):
            pass

        async def price_request(self, **kw):
            if pricing_raises:
                raise RuntimeError("pricing boom")
            raise AssertionError("price_request unexpectedly called")

    monkeypatch.setattr(charging, "_overlay_billing", lambda pg, cfg: object())
    monkeypatch.setattr(bs_mod, "BillingService", _FakeBilling)
    monkeypatch.setattr(ps_mod, "PricingService", _FakePricing)
    return captured


@pytest.mark.asyncio
async def test_charge_usage_floors_when_no_provider_usage(monkeypatch) -> None:
    captured = _patch_billing(monkeypatch, pricing_raises=False)
    credits = await charging._charge_usage(
        pg_connector=FakeConnector(FakeDBSession()),
        redis_client=None,
        user_id="u1",
        execution_result={"total_tokens": 0, "reply_chars_count": 42},
        thread_id="t",
        job_id="job-1",
        resolved_model="m",
        config=object(),
        reservation_id="r1",
        reserved_estimate=25,
    )
    assert credits == 25  # floor списан, а не 0
    assert captured["charged"]["credits"] == 25
    assert captured["charged"]["reservation_id"] == "r1"
    assert captured["charged"]["idempotency_key"] == "job-1"
    assert captured["charged"]["metadata"]["billing_fallback"] == "no_provider_usage_floor"


@pytest.mark.asyncio
async def test_charge_usage_floors_when_pricing_fails(monkeypatch) -> None:
    captured = _patch_billing(monkeypatch, pricing_raises=True)
    credits = await charging._charge_usage(
        pg_connector=FakeConnector(FakeDBSession()),
        redis_client=None,
        user_id="u1",
        execution_result={
            "total_tokens": 100,
            "reply_chars_count": 10,
            "per_call_usage": [{"model": "m", "prompt": 50, "completion": 50}],
        },
        thread_id="t",
        job_id="job-2",
        resolved_model="m",
        config=object(),
        reservation_id="r2",
        reserved_estimate=30,
    )
    assert credits == 30  # тарификация упала -> floor, не 0
    assert captured["charged"]["credits"] == 30
    assert captured["charged"]["tokens"] == 100
    assert captured["charged"]["metadata"]["billing_fallback"] == "pricing_failed_floor"


@pytest.mark.asyncio
async def test_charge_usage_releases_when_no_usage_and_no_reply(monkeypatch) -> None:
    # Нет usage И ответ не отдавался -> ничего не списываем, резерв отпускаем.
    captured = _patch_billing(monkeypatch, pricing_raises=False)
    credits = await charging._charge_usage(
        pg_connector=FakeConnector(FakeDBSession()),
        redis_client=None,
        user_id="u1",
        execution_result={"total_tokens": 0, "reply_chars_count": 0},
        thread_id="t",
        job_id="job-3",
        resolved_model="m",
        config=object(),
        reservation_id="r3",
        reserved_estimate=25,
    )
    assert credits == 0
    assert captured["charged"] is None  # charge НЕ вызывался
    assert captured["released"] is True


@pytest.mark.asyncio
async def test_charge_usage_no_floor_without_reservation(monkeypatch) -> None:
    # Нет резерва (reserved_estimate=0, напр. память) и нет usage -> не выдумываем floor.
    captured = _patch_billing(monkeypatch, pricing_raises=False)
    credits = await charging._charge_usage(
        pg_connector=FakeConnector(FakeDBSession()),
        redis_client=None,
        user_id="u1",
        execution_result={"total_tokens": 0, "reply_chars_count": 99},
        thread_id="t",
        job_id="job-4",
        resolved_model="m",
        config=object(),
        reservation_id=None,
        reserved_estimate=0,
    )
    assert credits == 0
    assert captured["charged"] is None
