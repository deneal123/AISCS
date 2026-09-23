"""Фаза 2 биллинга: ценообразование (формула cost→credits + fallback + запись).

Чистая формула и сервис тарификации тестируются без БД (фейковый репозиторий
и FakeDBSession).
"""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from service.services.billing.application.pricing_service import PricingService, classify_model
from service.services.billing.domain.pricing import (
    ModelPrice,
    PricingParams,
    call_cost_rub,
    compute_credits,
    resolve_model_price,
)
from service.services.billing.persistence.billing_repository import BillingRepository
from tests.test_helpers import FakeConnector, FakeDBSession

_PARAMS = PricingParams(
    credit_unit_rub=Decimal("0.01"),
    margin_multiplier=Decimal("2.5"),
    complexity_factor_complex=Decimal("1.15"),
    min_credits_per_request=1,
)


# --------------------------------------------------------------------------- #
# Доменная формула                                                            #
# --------------------------------------------------------------------------- #
def test_call_cost_rub_basic() -> None:
    price = ModelPrice(Decimal("2"), Decimal("6"))
    assert call_cost_rub(1000, 1000, price) == Decimal("8")
    assert call_cost_rub(500, 0, price) == Decimal("1")


def test_compute_credits_applies_margin() -> None:
    price = ModelPrice(Decimal("2"), Decimal("6"))
    result = compute_credits(
        per_call_prices=[(1000, 1000, price)],
        tool_surcharges_rub=[],
        is_complex=False,
        params=_PARAMS,
    )
    assert result.raw_cost_rub == Decimal("8")
    assert result.billable_rub == Decimal("20.0")
    assert result.credits == 2000  # ceil(20 / 0.01)


def test_compute_credits_complexity_factor() -> None:
    price = ModelPrice(Decimal("2"), Decimal("6"))
    result = compute_credits(
        per_call_prices=[(1000, 1000, price)],
        tool_surcharges_rub=[],
        is_complex=True,
        params=_PARAMS,
    )
    assert result.credits == 2300  # 8 * 2.5 * 1.15 = 23 → /0.01


def test_compute_credits_per_model_margin_override() -> None:
    price = ModelPrice(Decimal("2"), Decimal("6"), margin_override=Decimal("3"))
    result = compute_credits(
        per_call_prices=[(1000, 1000, price)],
        tool_surcharges_rub=[],
        is_complex=False,
        params=_PARAMS,
    )
    assert result.credits == 2400  # 8 * 3 = 24 → /0.01


def test_compute_credits_tool_surcharges() -> None:
    price = ModelPrice(Decimal("2"), Decimal("6"))
    result = compute_credits(
        per_call_prices=[(1000, 1000, price)],
        tool_surcharges_rub=[Decimal("3")],  # deep_research
        is_complex=False,
        params=_PARAMS,
    )
    # raw = 8 + 3 = 11; billable = 8*2.5 + 3*2.5 = 27.5 → 2750 кредитов
    assert result.raw_cost_rub == Decimal("11")
    assert result.credits == 2750


def test_compute_credits_min_floor() -> None:
    params = PricingParams(
        credit_unit_rub=Decimal("0.01"),
        margin_multiplier=Decimal("2.5"),
        complexity_factor_complex=Decimal("1.15"),
        min_credits_per_request=5,
    )
    price = ModelPrice(Decimal("2"), Decimal("6"))
    result = compute_credits(
        per_call_prices=[(1, 0, price)],
        tool_surcharges_rub=[],
        is_complex=False,
        params=params,
    )
    assert result.credits == 5  # ceil(0.005/0.01)=1 → floored to 5


def test_compute_credits_rejects_bad_unit() -> None:
    bad = PricingParams(Decimal("0"), Decimal("2.5"), Decimal("1.15"), 1)
    with pytest.raises(ValueError):
        compute_credits(per_call_prices=[], tool_surcharges_rub=[], is_complex=False, params=bad)


# --------------------------------------------------------------------------- #
# Fallback-цепочка цены                                                       #
# --------------------------------------------------------------------------- #
def test_resolve_model_price_fallback_chain() -> None:
    registry = {"gpt-x": ModelPrice(Decimal("1"), Decimal("3"))}
    class_prices = {
        "fast": ModelPrice(Decimal("0.3"), Decimal("0.9")),
        "large": ModelPrice(Decimal("3"), Decimal("9")),
    }
    default = ModelPrice(Decimal("2"), Decimal("6"))

    def _resolve(model):
        return resolve_model_price(
            model,
            registry=registry,
            classify=classify_model,
            class_prices=class_prices,
            default_price=default,
        )

    assert _resolve("gpt-x").price_in_rub_per_1k == Decimal("1")  # registry
    assert _resolve("qwen-7b").price_in_rub_per_1k == Decimal("0.3")  # class fast
    assert _resolve("model-70b").price_in_rub_per_1k == Decimal("3")  # class large
    assert _resolve("randomthing").price_in_rub_per_1k == Decimal("2")  # default
    assert _resolve(None).price_in_rub_per_1k == Decimal("2")  # default


def test_resolve_model_price_zero_explicit_falls_back() -> None:
    # Явная цена 0/0 = «не задана» → биллим по классу/дефолту, а НЕ в ноль (защита
    # от моделей вроде flux/lyria, импортированных с нулевой ценой). Частичный ноль
    # (эмбеддинги: вход>0, выход=0) — валиден и сохраняется.
    registry = {
        "flux": ModelPrice(Decimal("0"), Decimal("0")),  # media-модель без цены
        "embed": ModelPrice(Decimal("0.5"), Decimal("0")),  # эмбеддинг: выход 0 ок
    }
    class_prices = {"large": ModelPrice(Decimal("3"), Decimal("9"))}
    default = ModelPrice(Decimal("2"), Decimal("6"))

    def _resolve(model):
        return resolve_model_price(
            model,
            registry=registry,
            classify=lambda _m: None,
            class_prices=class_prices,
            default_price=default,
        )

    assert _resolve("flux").price_in_rub_per_1k == Decimal("2")  # 0/0 → дефолт
    assert _resolve("flux").price_out_rub_per_1k == Decimal("6")
    assert _resolve("embed").price_in_rub_per_1k == Decimal("0.5")  # частичный 0 сохранён
    assert _resolve("embed").price_out_rub_per_1k == Decimal("0")


def test_resolve_model_price_prefers_actual_provider() -> None:
    registry = {
        ("routerai", "openai/gpt-4o-mini"): ModelPrice(Decimal("0.02"), Decimal("0.08")),
        ("openrouter", "openai/gpt-4o-mini"): ModelPrice(Decimal("0.015"), Decimal("0.06")),
        ("", "openai/gpt-4o-mini"): ModelPrice(Decimal("9"), Decimal("9")),
    }
    default = ModelPrice(Decimal("2"), Decimal("6"))

    routerai = resolve_model_price(
        "openai/gpt-4o-mini",
        provider="routerai",
        registry=registry,
        classify=lambda _m: None,
        class_prices={},
        default_price=default,
    )
    openrouter = resolve_model_price(
        "openai/gpt-4o-mini",
        provider="openrouter",
        registry=registry,
        classify=lambda _m: None,
        class_prices={},
        default_price=default,
    )
    assert routerai.price_in_rub_per_1k == Decimal("0.02")
    assert openrouter.price_in_rub_per_1k == Decimal("0.015")


# --------------------------------------------------------------------------- #
# PricingService                                                              #
# --------------------------------------------------------------------------- #
class _FakePricingRepo:
    def __init__(self, mapping=None):
        self._mapping = mapping or {}

    async def fetch_pricing_map(self):
        return self._mapping


def _cfg(**overrides):
    base = dict(
        credit_unit_rub=0.01,
        margin_multiplier=2.5,
        min_margin=2.0,
        complexity_factor_complex=1.15,
        min_credits_per_request=1,
        default_price_in_rub_per_1k=2.0,
        default_price_out_rub_per_1k=6.0,
        class_prices_rub_per_1k={"fast": [0.3, 0.9], "large": [3.0, 9.0]},
        tool_surcharge_rub={"web_search": 1.0, "deep_research": 3.0},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_pricing_service_registry_hit() -> None:
    repo = _FakePricingRepo({"m1": ModelPrice(Decimal("1"), Decimal("3"))})
    svc = PricingService(repo, _cfg())
    result = await svc.price_request(
        per_call_usage=[{"model": "m1", "prompt": 1000, "completion": 1000}],
        tools=[],
        is_complex=False,
    )
    assert result.raw_cost_rub == Decimal("4")  # 1 + 3
    assert result.credits == 1000  # 4*2.5=10 → /0.01


@pytest.mark.asyncio
async def test_pricing_service_default_and_class_fallback() -> None:
    svc = PricingService(_FakePricingRepo(), _cfg())

    default = await svc.price_request(
        per_call_usage=[{"model": "zzz", "prompt": 1000, "completion": 1000}],
        tools=[],
        is_complex=False,
    )
    assert default.credits == 2000  # default 2/6 → cost 8 → 2000

    fast = await svc.price_request(
        per_call_usage=[{"model": "qwen-7b", "prompt": 1000, "completion": 1000}],
        tools=[],
        is_complex=False,
    )
    assert fast.credits == 300  # class fast 0.3/0.9 → cost 1.2 → 3.0 → 300


@pytest.mark.asyncio
async def test_pricing_service_tool_surcharge_and_complexity() -> None:
    repo = _FakePricingRepo({"m1": ModelPrice(Decimal("1"), Decimal("3"))})
    svc = PricingService(repo, _cfg())
    result = await svc.price_request(
        per_call_usage=[{"model": "m1", "prompt": 1000, "completion": 1000}],
        tools=["deep_research"],
        is_complex=True,
    )
    # raw = 4 + 3 = 7; billable = (4*2.5 + 3*2.5) * 1.15 = 17.5 * 1.15 = 20.125
    assert result.raw_cost_rub == Decimal("7")
    assert result.credits == 2013  # ceil(2012.5)


@pytest.mark.asyncio
async def test_pricing_service_margin_floor() -> None:
    # глобальная маржа ниже min_margin → берётся min_margin
    svc = PricingService(
        _FakePricingRepo({"m1": ModelPrice(Decimal("1"), Decimal("3"))}),
        _cfg(margin_multiplier=1.0, min_margin=2.0),
    )
    result = await svc.price_request(
        per_call_usage=[{"model": "m1", "prompt": 1000, "completion": 1000}],
        tools=[],
        is_complex=False,
    )
    assert result.credits == 800  # 4 * 2.0 = 8 → /0.01


@pytest.mark.asyncio
async def test_pricing_service_clamps_low_override() -> None:
    # пер-модельный override ниже min_margin не должен опускать маржу
    svc = PricingService(
        _FakePricingRepo(
            {"m1": ModelPrice(Decimal("1"), Decimal("3"), margin_override=Decimal("1.0"))}
        ),
        _cfg(),
    )
    result = await svc.price_request(
        per_call_usage=[{"model": "m1", "prompt": 1000, "completion": 1000}],
        tools=[],
        is_complex=False,
    )
    assert result.credits == 800  # clamp до min_margin 2.0 → 4*2=8 → 800


# --------------------------------------------------------------------------- #
# BillingRepository.record_usage                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_record_usage_writes_event_and_daily() -> None:
    session = FakeDBSession()
    repo = BillingRepository(FakeConnector(session))

    await repo.record_usage(
        user_id="22222222-2222-2222-2222-222222222222",
        tokens=150,
        credits=42,
        raw_cost_rub=8.5,
        metadata={"model": "m1", "prompt": 120, "completion": 30},
    )

    assert len(session.executed) == 2
    event_sql, event_params = session.executed[0]
    daily_sql, daily_params = session.executed[1]

    assert "INSERT INTO profile.billing_events" in event_sql
    assert event_params["tokens"] == 150
    meta = json.loads(event_params["metadata"])
    assert meta["credits"] == 42
    assert meta["raw_cost_rub"] == 8.5
    assert meta["model"] == "m1"

    assert "INSERT INTO profile.usage_daily" in daily_sql
    assert "ON CONFLICT" in daily_sql
    assert daily_params["credits"] == 42
    assert daily_params["tokens"] == 150
    assert daily_params["raw_cost"] == 8.5

    assert session._committed is True
