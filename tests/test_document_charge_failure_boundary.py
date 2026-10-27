"""A durable audit must not mistake the legacy zero fallback for a committed charge."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.services.chat.infrastructure.chat_worker.billing.charging import _charge_usage


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [False, True])
async def test_charge_failure_is_retryable_for_durable_callers_only(strict, caplog):
    # Invalid token input fails before pricing, DB access, or balance mutation.
    kwargs = dict(
        pg_connector=object(),
        redis_client=object(),
        user_id="opaque-user",
        execution_result={"total_tokens": "PRIVATE_FAILURE_MARKER"},
        thread_id="opaque-thread",
        job_id="opaque-job",
        resolved_model=None,
        config=object(),
        require_persisted=strict,
    )
    if strict:
        with pytest.raises(RuntimeError, match="^usage_charge_unavailable$") as error:
            await _charge_usage(**kwargs)
        assert error.value.__cause__ is None
    else:
        assert await _charge_usage(**kwargs) == 0
    assert "PRIVATE_FAILURE_MARKER" not in caplog.text


@pytest.mark.asyncio
async def test_durable_pricing_failure_does_not_persist_zero_charge(monkeypatch, caplog):
    from service.services.billing.application import billing_service, pricing_service
    from service.services.chat.infrastructure.chat_worker.billing import charging

    pricing = SimpleNamespace(price_request=AsyncMock(side_effect=RuntimeError("PRIVATE_PRICING")))
    charge = AsyncMock()
    monkeypatch.setattr(pricing_service, "PricingService", lambda *_a: pricing)
    monkeypatch.setattr(
        billing_service, "BillingService", lambda *_a: SimpleNamespace(charge=charge)
    )
    monkeypatch.setattr(charging, "_overlay_billing", lambda *_a: object())
    with pytest.raises(RuntimeError, match="^usage_charge_unavailable$"):
        await charging._charge_usage(
            pg_connector=object(),
            redis_client=None,
            user_id="opaque-user",
            execution_result={
                "total_tokens": 33,
                "prompt_tokens": 30,
                "completion_tokens": 3,
                "reply_chars_count": 1,
                "per_call_usage": [{"model": "vision", "prompt": 30, "completion": 3}],
            },
            thread_id="opaque-thread",
            job_id="opaque-job",
            resolved_model="vision",
            config=object(),
            require_persisted=True,
        )
    pricing.price_request.assert_awaited_once()
    charge.assert_not_awaited()
    assert "PRIVATE_PRICING" not in caplog.text
