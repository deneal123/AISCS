from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.billing.domain.pricing import ModelPrice
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

logger = logging.getLogger(__name__)


class PricingRepository(BaseRepository):
    """Доступ к ручному реестру цен моделей (profile.model_pricing)."""

    @connection()
    async def fetch_pricing_map(
        self, session: AsyncSession | None = None
    ) -> dict[object, ModelPrice]:
        session = require_session(session)
        result = await session.execute(
            text(
                "SELECT provider, model_id, price_in_rub_per_1k, "
                "price_out_rub_per_1k, margin_override "
                "FROM profile.model_pricing"
            )
        )
        out: dict[object, ModelPrice] = {}
        for row in result.fetchall():
            out[(str(row[0] or "").lower(), str(row[1]))] = ModelPrice(
                price_in_rub_per_1k=Decimal(str(row[2])),
                price_out_rub_per_1k=Decimal(str(row[3])),
                margin_override=Decimal(str(row[4])) if row[4] is not None else None,
            )
        return out

    @connection()
    async def upsert_model_pricing(
        self,
        *,
        provider: str = "",
        model_id: str,
        price_in: float,
        price_out: float,
        margin_override: float | None = None,
        model_class: str | None = None,
        updated_by: str | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        """Создать/обновить цену модели (для сидинга и админ-CRUD)."""
        session = require_session(session)
        await session.execute(
            text(
                "INSERT INTO profile.model_pricing "
                "(provider, model_id, price_in_rub_per_1k, price_out_rub_per_1k, margin_override, "
                "model_class, updated_by) "
                "VALUES (:provider, :model_id, :price_in, :price_out, :margin_override, "
                ":model_class, :updated_by) "
                "ON CONFLICT (provider, model_id) DO UPDATE SET "
                "price_in_rub_per_1k = EXCLUDED.price_in_rub_per_1k, "
                "price_out_rub_per_1k = EXCLUDED.price_out_rub_per_1k, "
                "margin_override = EXCLUDED.margin_override, "
                "model_class = EXCLUDED.model_class, "
                "updated_by = EXCLUDED.updated_by, "
                "updated_at = now()"
            ),
            {
                "provider": (provider or "").strip().lower(),
                "model_id": model_id,
                "price_in": float(price_in),
                "price_out": float(price_out),
                "margin_override": float(margin_override) if margin_override is not None else None,
                "model_class": model_class,
                "updated_by": updated_by,
            },
        )
