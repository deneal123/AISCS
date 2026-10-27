"""Нулевой тариф использует обычный резерв, не отключая денежный допуск."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.services.chat.infrastructure.chat_worker.billing.reservation import preflight
from tests.test_billing_reservation_worker import _billing_cfg
from tests.test_helpers import FakeConnector, FakeDBSession

MODEL = "qwen2.5-1.5b-instruct"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", [None, "ide_harness", "pdf_harness"])
async def test_zero_token_price_produces_zero_hold(route):
    assert (
        await preflight.estimate_reservation_credits(
            pg_connector=FakeConnector(FakeDBSession()),
            billing_cfg=_billing_cfg(),
            text="Прочитай проект",
            selected_model=MODEL,
            route=route,
        )
        == 0
    )


@pytest.mark.asyncio
async def test_paid_tools_still_require_a_hold():
    assert (
        await preflight.estimate_reservation_credits(
            pg_connector=FakeConnector(FakeDBSession()),
            billing_cfg=_billing_cfg(tool_surcharge_rub={"workspace_tool": 1}),
            text="Прочитай проект",
            selected_model=MODEL,
            route="ide_harness",
        )
        > 0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model,estimate,held",
    [(MODEL, 0, "owned-zero-hold"), (MODEL, 10, None), ("GigaChat-2", 10, None)],
)
async def test_zero_balance_only_admits_a_confirmed_free_reservation(
    monkeypatch, model, estimate, held
):
    from service.services.billing.application import billing_service

    billing = SimpleNamespace(
        has_sufficient_credits=AsyncMock(return_value=False), reserve=AsyncMock(return_value=held)
    )
    monkeypatch.setattr(billing_service, "BillingService", lambda *_: billing)
    insufficient = AsyncMock(return_value={"insufficient_credits": True})
    estimate_call = AsyncMock(return_value=estimate)
    result, reservation, amount = await preflight.reserve_credits_or_short_circuit(
        pg_connector=None,
        config=None,
        publisher=None,
        job_repo=None,
        session=None,
        job_id="job",
        thread_id="thread",
        text="Запрос",
        user_id="owner",
        selected_model=model,
        context_chars=0,
        attachments=None,
        expensive_run_confirmed=False,
        overlay_billing=lambda *_: SimpleNamespace(
            insufficient_credits_message="Недостаточно кредитов"
        ),
        estimate_credits=estimate_call,
        emit_expensive=AsyncMock(),
        emit_insufficient=insufficient,
    )
    if held:
        assert result is None and reservation == held and amount == 0
        assert billing.reserve.await_args.kwargs["credits"] == 0
        insufficient.assert_not_awaited()
    else:
        assert result == {"insufficient_credits": True} and reservation is None
    if model != MODEL:
        billing.reserve.assert_not_awaited()
        estimate_call.assert_not_awaited()
