from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.billing.persistence.sql import (
    _DELETE_SYNCED_PRICING_SQL,
    _UPSERT_SYNCED_PRICING_SQL,
)
from service.shared.repositories.decorators.session_processor import connection, require_session


class SyncedPricingMixin:
    """Persistence operations that replace provider-owned pricing catalogs."""

    @connection()
    async def replace_synced_pricing(
        self,
        *,
        catalogs: list[dict[str, Any]],
        session: AsyncSession | None = None,
    ) -> dict[str, int]:
        """Atomically replace only prior provider-sync rows, never manual overrides."""
        session = require_session(session)
        replaced = 0
        deleted = 0
        for catalog in catalogs:
            provider = str(catalog["provider"]).strip().lower()
            source = str(catalog["source"])
            rows = list(catalog["rows"])
            if not provider or not source.startswith(f"sync:{provider}:") or not rows:
                raise ValueError("Invalid provider pricing catalog")
            result = await session.execute(
                text(_DELETE_SYNCED_PRICING_SQL),
                {"provider": provider, "source_prefix": f"sync:{provider}:%"},
            )
            deleted += int(result.rowcount or 0)
            await session.execute(
                text(_UPSERT_SYNCED_PRICING_SQL),
                [
                    {
                        "provider": provider,
                        "model_id": model_id,
                        "price_in": price_in,
                        "price_out": price_out,
                        "updated_by": source,
                        "source_prefix": f"sync:{provider}:%",
                    }
                    for model_id, price_in, price_out in rows
                ],
            )
            replaced += len(rows)
        return {"providers": len(catalogs), "replaced": replaced, "deleted": deleted}
