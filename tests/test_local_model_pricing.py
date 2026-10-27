"""Бесплатная локальная модель не отменяет оплату облачных вызовов и инструментов."""

from decimal import Decimal

import pytest

from service.services.billing.domain.pricing import (
    ModelPrice,
    PricingParams,
    compute_credits,
    resolve_model_price,
)
from service.shared.model_class import is_not_pricier_than

MODEL = "qwen2.5-1.5b-instruct"
PAID = ModelPrice(Decimal(2), Decimal(4))
PARAMS = PricingParams(Decimal("0.01"), Decimal(2), Decimal("1.2"), 10)


def resolve(model=MODEL, provider=None):
    return resolve_model_price(
        model,
        provider=provider,
        registry={},
        classify=lambda _: None,
        class_prices={},
        default_price=PAID,
    )


@pytest.mark.parametrize("provider", [None, "local"])
def test_local_usage_has_no_request_minimum(provider):
    price = resolve(provider=provider)
    assert price.is_free
    result = compute_credits(
        per_call_prices=[(4000, 1200, price)],
        tool_surcharges_rub=[],
        is_complex=True,
        params=PARAMS,
    )
    assert result.credits == result.raw_cost_rub == result.billable_rub == 0


@pytest.mark.parametrize(
    "model,provider",
    [(MODEL, "routerai"), ("local/other", None), ("liquid/lfm2.5-1.2b-instruct", None)],
)
def test_foreign_or_unknown_models_are_not_free(model, provider):
    assert resolve(model, provider) == PAID


def test_historical_local_receipts_remain_free_after_model_replacement():
    assert resolve("lfm2.5-1.2b-instruct", "local").is_free
    assert resolve("lfm2.5-1.2b-instruct", "routerai") == PAID


def test_tools_and_mixed_calls_remain_billable():
    for calls, surcharges in [
        ([(1000, 0, resolve())], [Decimal(1)]),
        ([(1000, 0, resolve()), (1000, 0, PAID)], []),
    ]:
        assert (
            compute_credits(
                per_call_prices=calls,
                tool_surcharges_rub=surcharges,
                is_complex=False,
                params=PARAMS,
            ).credits
            > 0
        )


def test_free_selection_does_not_allow_paid_failover_by_model_class():
    assert is_not_pricier_than(MODEL, MODEL)
    assert not is_not_pricier_than("gpt-4o-mini", MODEL)
    assert not is_not_pricier_than("GigaChat-2", MODEL)


def test_frozen_tariff_uses_the_same_free_policy():
    from service.services.billing.application.frozen_pricing import FrozenPricing, TariffEntry

    fallback = TariffEntry(model="default", incoming="2", outgoing="4")
    frozen = FrozenPricing(
        entries=(),
        classes=(),
        default=fallback,
        credit_unit="0.01",
        margin="2",
        complexity="1.2",
        minimum=10,
        minimum_margin="1",
        surcharges={"web": "1"},
    )
    calls = [{"provider": "local", "model": MODEL, "prompt": 4000, "completion": 1200}]
    assert frozen.price(calls).credits == 0
    tools = frozen.price(calls, ["web"])
    assert tools.credits > 0
    assert tools.surcharge_credits == tools.credits
    foreign = [{**calls[0], "provider": "routerai", "model": "cloud-model"}]
    assert frozen.task_price(foreign, selected_model=MODEL).credits > 0


def test_zero_budget_preserves_receipts_and_detects_any_paid_dispatch():
    from service.services.chat.persistence.harness.state import priced_totals
    from service.shared.harness_protocol import Admission
    from tests.test_harness_runtime_contract import admission

    accepted = Admission.model_validate(
        {**admission().model_dump(mode="json"), "credit_limit": 0, "pricing_model": MODEL}
    )
    from service.services.billing.application.frozen_pricing import FrozenPricing

    tariff = FrozenPricing(
        entries=(),
        classes=(),
        default={"model": "default", "incoming": "2", "outgoing": "4"},
        credit_unit="0.01",
        margin="2",
        complexity="1.2",
        minimum=10,
        minimum_margin="1",
        surcharges={},
    )
    row = {"tariff": tariff.model_dump(mode="json"), "admission": accepted.model_dump(mode="json")}
    request = {"provider": "local", "model": MODEL, "prompt": 100, "completion": 20}
    assert priced_totals(row, [{"state": "allocated", "request": request}]) == (0, 0)
    assert priced_totals(
        row,
        [{"state": "succeeded", "request": request, "receipt": {"prompt": 100, "completion": 20}}],
    ) == (0, 0)
    foreign = {**request, "provider": "routerai"}
    assert priced_totals(row, [{"state": "allocated", "request": foreign}])[1] > 0
