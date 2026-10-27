"""Request pricing policy without balance, reservation or settlement authority.

The quote preserves the worker's existing floor/substitution policy. A quote is
not a debit receipt: only charging.py may submit it to BillingService.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from service.services.billing.domain.pricing import PriceResult
from service.shared.model_class import is_free_local_model

logger = logging.getLogger(__name__)


class RequestPricing(Protocol):
    async def price_request(
        self, *, per_call_usage: list[dict[str, Any]], tools: list[str], is_complex: bool
    ) -> PriceResult: ...


@dataclass(frozen=True, slots=True)
class UsagePricingInput:
    total_tokens: int
    reply_produced: bool
    reserved_estimate: int
    per_call_usage: list[dict[str, Any]]
    chosen_model: str | None
    tools: list[str]
    is_complex: bool
    reconstructed: bool = False


@dataclass(frozen=True, slots=True)
class ChargeQuote:
    credits: int
    raw_cost_rub: float
    fallback: str | None = None


async def _chosen_model_ceiling(pricing: RequestPricing, inputs: UsagePricingInput) -> int | None:
    """Reprice the same calls, not an extra inference, at the selected model's tariff."""
    if (
        not inputs.chosen_model
        or not inputs.per_call_usage
        or is_free_local_model(inputs.chosen_model)
    ):
        return None
    if not any(
        str(call.get("model") or "") != str(inputs.chosen_model) for call in inputs.per_call_usage
    ):
        return None
    price = await pricing.price_request(
        per_call_usage=[{**call, "model": inputs.chosen_model} for call in inputs.per_call_usage],
        tools=inputs.tools,
        is_complex=inputs.is_complex,
    )
    return int(price.credits)


async def quote_usage(
    inputs: UsagePricingInput,
    *,
    pricing_factory: Callable[[], RequestPricing],
    require_persisted: bool = False,
    breakdown_out: dict[str, Any] | None = None,
) -> ChargeQuote | None:
    """None means no payable usage/floor; the caller remains responsible for releasing its hold.

    Pricing construction stays lazy and inside the failure boundary. Missing usage
    must not touch the pricing service; strict durable callers never get a pricing-
    failure floor. Cancellation is not converted into a quote or retried.
    """
    if inputs.total_tokens <= 0:
        if not (inputs.reply_produced and inputs.reserved_estimate > 0):
            return None
        return ChargeQuote(int(inputs.reserved_estimate), 0.0, "no_provider_usage_floor")

    fallback = "per_call_reconstructed" if inputs.reconstructed else None
    try:
        pricing = pricing_factory()
        price = await pricing.price_request(
            per_call_usage=inputs.per_call_usage, tools=inputs.tools, is_complex=inputs.is_complex
        )
        credits, raw_cost = price.credits, float(price.raw_cost_rub)
        if breakdown_out is not None and price.surcharge_credits > 0:
            breakdown_out["surcharge_credits"] = int(price.surcharge_credits)
            breakdown_out["surcharged_tools"] = list(inputs.tools)
        capped = await _chosen_model_ceiling(pricing, inputs)
        if capped is not None and capped < credits:
            logger.warning(
                "provider substitution charge capped",
                extra={"component": "billing", "failure_code": "model_substitution"},
            )
            credits, fallback = capped, "model_substitution_capped"
            # The cap reprices the whole quote; the prior surcharge share is no
            # longer factual. Preserve the existing mutable breakdown contract.
            if breakdown_out is not None:
                breakdown_out.clear()
        return ChargeQuote(credits, raw_cost, fallback)
    except Exception:
        if require_persisted:
            raise RuntimeError("usage_charge_unavailable") from None
        logger.warning(
            "pricing failed; applying reserved floor",
            extra={"component": "billing", "failure_code": "pricing"},
        )
        credits = int(inputs.reserved_estimate) if inputs.reserved_estimate > 0 else 0
        return ChargeQuote(
            credits, 0.0, "pricing_failed_floor" if credits > 0 else "pricing_failed_zero"
        )
