"""Резерв кредитов ДО вызова LLM в chat-воркере (анти-TOCTOU precheck).

Проверяем только оценку резерва (чистая композиция + reserve_safety) — сама
атомарность резерва/списания уже покрыта test_billing_wallets.py на уровне
BillingRepository. Реальную SQL-семантику Postgres прогон миграций на живой
БД проверяет (в песочнице её нет).
"""

from types import SimpleNamespace

import pytest

from service.services.chat.infrastructure.chat_worker_tasks import (
    _estimate_reservation_credits,
)
from tests.test_helpers import FakeConnector, FakeDBSession


def _billing_cfg(**overrides):
    base = dict(
        credit_unit_rub=0.01,
        margin_multiplier=2.5,
        min_margin=2.0,
        complexity_factor_complex=1.15,
        min_credits_per_request=1,
        default_price_in_rub_per_1k=2.0,
        default_price_out_rub_per_1k=6.0,
        class_prices_rub_per_1k={},
        tool_surcharge_rub={},
        reserve_safety=1.2,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_estimate_reservation_credits_is_positive() -> None:
    connector = FakeConnector(FakeDBSession())
    estimate = await _estimate_reservation_credits(
        pg_connector=connector, billing_cfg=_billing_cfg(), text="hello", selected_model=None
    )
    assert estimate > 0


@pytest.mark.asyncio
async def test_estimate_reservation_credits_scales_with_reserve_safety() -> None:
    connector = FakeConnector(FakeDBSession())
    low = await _estimate_reservation_credits(
        pg_connector=connector,
        billing_cfg=_billing_cfg(reserve_safety=1.0),
        text="hello",
        selected_model=None,
    )
    high = await _estimate_reservation_credits(
        pg_connector=connector,
        billing_cfg=_billing_cfg(reserve_safety=2.0),
        text="hello",
        selected_model=None,
    )
    # ceil() rounding means "high" isn't exactly 2x "low", but must be at least
    # as large after doubling the safety margin.
    assert high >= low * 2 - 1


@pytest.mark.asyncio
async def test_estimate_reservation_credits_longer_prompt_costs_more() -> None:
    connector = FakeConnector(FakeDBSession())
    short = await _estimate_reservation_credits(
        pg_connector=connector, billing_cfg=_billing_cfg(), text="hi", selected_model=None
    )
    long = await _estimate_reservation_credits(
        pg_connector=connector,
        billing_cfg=_billing_cfg(),
        text="x" * 20_000,
        selected_model=None,
    )
    assert long > short
