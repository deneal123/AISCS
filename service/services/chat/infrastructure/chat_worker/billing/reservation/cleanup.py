"""Bounded, owner-scoped hold compensation independent of caller disconnects."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)
RELEASE_TIMEOUT_SECONDS = 30


async def release_owned_hold(
    *,
    pg_connector: Any,
    config: Any,
    user_id: str | None,
    reservation_id: str | None,
    overlay_billing: Callable[..., Any],
) -> None:
    """Drain one bounded attempt, then propagate parent cancellation; never retry."""
    if not reservation_id or not user_id:
        return

    async def attempt() -> None:
        try:
            from service.services.billing.application.billing_service import BillingService
            from service.services.billing.persistence.billing_repository import BillingRepository

            async with asyncio.timeout(RELEASE_TIMEOUT_SECONDS):
                billing_cfg = overlay_billing(pg_connector, config)
                await BillingService(
                    BillingRepository(pg_connector), billing_cfg
                ).release_reservation(reservation_id, user_id=user_id)
        except Exception:
            logger.debug(
                "credit reservation release failed",
                extra={"component": "billing", "failure_code": "reservation_release"},
            )

    cleanup = asyncio.create_task(attempt())
    interrupted = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            interrupted = True
    cleanup.result()
    if interrupted:
        raise asyncio.CancelledError
