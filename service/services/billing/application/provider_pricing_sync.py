"""Orchestrate safe price-catalog replacement for the maintenance worker."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from service.services.billing.application.provider_catalog import fetch_provider_pricing_catalogs


class ProviderPricingSyncService:
    def __init__(
        self, repo: Any, *, fetch_catalogs: Callable = fetch_provider_pricing_catalogs
    ) -> None:
        self._repo = repo
        self._fetch_catalogs = fetch_catalogs

    async def refresh(self) -> dict[str, int]:
        """Fetch both provider catalogs before opening the one DB transaction."""
        catalogs = await asyncio.to_thread(self._fetch_catalogs)
        result = await self._repo.replace_synced_pricing(
            catalogs=[
                {"provider": catalog.provider, "rows": catalog.rows, "source": catalog.source}
                for catalog in catalogs
            ]
        )
        return {key: int(value) for key, value in result.items()}
