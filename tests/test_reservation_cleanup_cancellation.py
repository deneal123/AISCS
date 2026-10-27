"""A parent disconnect must not abort already-started owned hold compensation."""

import asyncio

import pytest

from service.services.chat.infrastructure.chat_worker.billing import charging


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", [1, 3])
async def test_started_release_settles_once_before_propagating_disconnect(
    monkeypatch, cancel_count
):
    from service.services.billing.application import billing_service

    entered, finish = asyncio.Event(), asyncio.Event()
    calls, settled = [], []

    class Billing:
        def __init__(self, *args):
            pass

        async def release_reservation(self, reservation_id, *, user_id):
            calls.append((user_id, reservation_id))
            entered.set()
            await finish.wait()
            settled.append(True)

    monkeypatch.setattr(billing_service, "BillingService", Billing)
    monkeypatch.setattr(charging, "_overlay_billing", lambda *args: object())
    task = asyncio.create_task(
        charging._release_reservation(
            pg_connector=object(), config=object(), user_id="owner", reservation_id="hold"
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        for _ in range(cancel_count):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done(), "disconnect aborted owned compensation"
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert calls == [("owner", "hold")]
        assert settled == [True]
    finally:
        finish.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["timeout", "failure"])
async def test_release_outage_is_bounded_private_and_not_retried(monkeypatch, caplog, mode):
    from service.services.billing.application import billing_service
    from service.services.chat.infrastructure.chat_worker.billing.reservation import (
        cleanup as reservation_cleanup,
    )

    calls, cancelled = [], []

    class Billing:
        def __init__(self, *args):
            pass

        async def release_reservation(self, reservation_id, *, user_id):
            calls.append((user_id, reservation_id))
            if mode == "failure":
                raise RuntimeError("private-reservation-error-marker")
            try:
                await asyncio.Future()
            finally:
                cancelled.append(True)

    monkeypatch.setattr(billing_service, "BillingService", Billing)
    monkeypatch.setattr(charging, "_overlay_billing", lambda *args: object())
    monkeypatch.setattr(reservation_cleanup, "RELEASE_TIMEOUT_SECONDS", 0.01)
    # main's service logger stops propagation; capture directly independent of test order.
    monkeypatch.setattr(reservation_cleanup.logger, "disabled", False)
    monkeypatch.setattr(reservation_cleanup.logger, "propagate", False)
    monkeypatch.setattr(reservation_cleanup.logger, "handlers", [caplog.handler])
    with caplog.at_level("DEBUG", logger=reservation_cleanup.__name__):
        await asyncio.wait_for(
            charging._release_reservation(
                pg_connector=object(), config=object(), user_id="owner", reservation_id="hold"
            ),
            timeout=1,
        )
    assert calls == [("owner", "hold")]
    assert cancelled == ([True] if mode == "timeout" else [])
    records = [record for record in caplog.records if record.name == reservation_cleanup.__name__]
    assert len(records) == 1
    assert records[0].component == "billing"
    assert records[0].failure_code == "reservation_release"
    assert records[0].exc_info is None
    assert "private-reservation-error-marker" not in caplog.text
