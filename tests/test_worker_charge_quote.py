"""Pricing decisions are independent of debit/hold ownership and preserve legacy policy."""

import asyncio
import logging
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from service.services.billing.domain.pricing import PriceResult
from service.services.chat.infrastructure.chat_worker.billing.quote import (
    ChargeQuote,
    UsagePricingInput,
    quote_usage,
)


def _inputs(**updates):
    return replace(
        UsagePricingInput(
            7,
            True,
            11,
            [{"model": "chosen", "prompt": 5, "completion": 2}],
            "chosen",
            ["web_search_tool"],
            False,
        ),
        **updates,
    )


def _price(credits=100, raw="3.5", surcharge=25):
    return PriceResult(credits, Decimal(raw), Decimal(raw), surcharge)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply,reserve,expected", [(False, 11, None), (True, 0, None), (False, 0, None), (True, 11, 11)]
)
async def test_missing_usage_never_constructs_pricing(reply, reserve, expected):
    factory = Mock(side_effect=AssertionError("pricing must not be constructed"))
    quote = await quote_usage(
        _inputs(total_tokens=0, reply_produced=reply, reserved_estimate=reserve),
        pricing_factory=factory,
        require_persisted=True,
    )
    assert quote == (
        None if expected is None else ChargeQuote(expected, 0.0, "no_provider_usage_floor")
    )
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_regular_quote_retains_tariff_cost_and_surcharge_without_second_lookup():
    inputs = _inputs(reconstructed=True)
    pricing = SimpleNamespace(price_request=AsyncMock(return_value=_price()))
    breakdown = {"existing": True}
    quote = await quote_usage(inputs, pricing_factory=lambda: pricing, breakdown_out=breakdown)
    assert quote == ChargeQuote(100, 3.5, "per_call_reconstructed")
    assert breakdown == {
        "existing": True,
        "surcharge_credits": 25,
        "surcharged_tools": ["web_search_tool"],
    }
    pricing.price_request.assert_awaited_once_with(
        per_call_usage=inputs.per_call_usage, tools=inputs.tools, is_complex=inputs.is_complex
    )


@pytest.mark.asyncio
async def test_substitution_cap_keeps_actual_provider_cost_and_discards_old_breakdown():
    inputs = _inputs(chosen_model="cheaper")
    pricing = SimpleNamespace(price_request=AsyncMock(side_effect=[_price(), _price(40, "1")]))
    breakdown = {"existing": True}
    quote = await quote_usage(inputs, pricing_factory=lambda: pricing, breakdown_out=breakdown)
    assert quote == ChargeQuote(40, 3.5, "model_substitution_capped")
    assert breakdown == {}
    assert pricing.price_request.await_count == 2
    assert pricing.price_request.await_args_list[1].kwargs["per_call_usage"] == [
        {"model": "cheaper", "prompt": 5, "completion": 2}
    ]
    assert inputs.per_call_usage[0]["model"] == "chosen"


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", [100, 150])
async def test_ceiling_cannot_raise_the_quote_or_remove_a_still_factual_surcharge(cap):
    pricing = SimpleNamespace(price_request=AsyncMock(side_effect=[_price(), _price(cap)]))
    breakdown = {}
    quote = await quote_usage(
        _inputs(chosen_model="other"), pricing_factory=lambda: pricing, breakdown_out=breakdown
    )
    assert quote == ChargeQuote(100, 3.5)
    assert breakdown["surcharge_credits"] == 25


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reserve,reason", [(11, "pricing_failed_floor"), (0, "pricing_failed_zero")]
)
async def test_constructor_failure_retains_existing_floor_and_redacts_error(
    caplog, reserve, reason
):
    marker = "private-pricing-failure-marker"
    factory = Mock(side_effect=RuntimeError(marker))
    with caplog.at_level(logging.WARNING):
        quote = await quote_usage(_inputs(reserved_estimate=reserve), pricing_factory=factory)
    assert quote == ChargeQuote(reserve, 0.0, reason)
    assert marker not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    factory.assert_called_once_with()


@pytest.mark.asyncio
async def test_strict_pricing_failure_is_not_a_floor_or_a_quote():
    factory = Mock(side_effect=RuntimeError("private-pricing-failure-marker"))
    with pytest.raises(RuntimeError, match="^usage_charge_unavailable$") as failure:
        await quote_usage(_inputs(), pricing_factory=factory, require_persisted=True)
    assert failure.value.__suppress_context__


@pytest.mark.asyncio
async def test_cancellation_is_neither_retried_nor_converted_to_a_floor():
    pricing = SimpleNamespace(price_request=AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await quote_usage(_inputs(), pricing_factory=lambda: pricing)
    assert pricing.price_request.await_count == 1
