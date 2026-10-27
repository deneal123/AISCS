"""Out-of-band discovery; never delay user traffic or run billable health pings."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from service.settings import config
from service.shared.agent_settings import runtime_settings
from service.shared.provider_policy_context import describe

logger = logging.getLogger(__name__)


async def refresh_catalogs() -> None:
    from service.domain.client.registry import _fetch_provider_catalogs
    from service.shared.model_catalog import get_openrouter_catalog

    # Do not probe a cold process's env-default "all enabled" before the backend
    # has delivered its authoritative policy. Explicit environment policy is OK.
    if not describe()["known"] and not runtime_settings.get_agents(
        "provider_enabled", config.agents.provider_enabled
    ):
        return
    catalogs = await _fetch_provider_catalogs(force_refresh=True)
    if catalogs:
        await get_openrouter_catalog()


async def _maintain() -> None:
    while True:
        try:
            await refresh_catalogs()
        except Exception:
            logger.warning(
                "provider inventory refresh unavailable", extra={"failure_code": "unavailable"}
            )
        known = describe()["known"] or bool(
            runtime_settings.get_agents("provider_enabled", config.agents.provider_enabled)
        )
        await asyncio.sleep(30 if known else 1)


@asynccontextmanager
async def maintain_catalogs():
    task = asyncio.create_task(_maintain(), name="provider-catalog-maintenance")
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
