"""Сервис ценообразования: registry + fallback-цепочка + формула кредитов.

Связывает БД-реестр цен (PricingRepository) с чистой доменной формулой
(domain.pricing). На вход — потребление запроса (per-call токены, инструменты,
флаг сложности), на выход — PriceResult (кредиты + себестоимость).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from service.services.billing.domain.pricing import (
    ModelPrice,
    PriceResult,
    PricingParams,
    compute_credits,
    resolve_model_price,
)
from service.services.billing.persistence.pricing_repository import PricingRepository
from service.shared.model_class import classify_model

# Классификатор класса модели переехал в service.shared.model_class: он нужен и реестру
# провайдеров (чтобы фейловер не подставлял модель ДОРОЖЕ выбранной), а тащить туда
# биллинг ради одного регэкспа — значит связать оплату с транспортом. Здесь оставлен
# реэкспорт: на `pricing_service.classify_model` уже ссылаются вызывающие и тесты.
__all__ = ["PricingService", "classify_model"]


class PricingService:
    def __init__(self, pricing_repo: PricingRepository, billing_config: Any) -> None:
        self._repo = pricing_repo
        self._cfg = billing_config

    # --- параметры из конфига -------------------------------------------- #
    def _min_margin(self) -> Decimal:
        return Decimal(str(self._cfg.min_margin))

    def _params(self) -> PricingParams:
        cfg = self._cfg
        # глобальная маржа не ниже защитной планки (инвариант: не работать в убыток)
        margin = max(Decimal(str(cfg.margin_multiplier)), self._min_margin())
        return PricingParams(
            credit_unit_rub=Decimal(str(cfg.credit_unit_rub)),
            margin_multiplier=margin,
            complexity_factor_complex=Decimal(str(cfg.complexity_factor_complex)),
            min_credits_per_request=int(cfg.min_credits_per_request),
        )

    def _default_price(self) -> ModelPrice:
        cfg = self._cfg
        return ModelPrice(
            price_in_rub_per_1k=Decimal(str(cfg.default_price_in_rub_per_1k)),
            price_out_rub_per_1k=Decimal(str(cfg.default_price_out_rub_per_1k)),
        )

    def _class_prices(self) -> dict[str, ModelPrice]:
        out: dict[str, ModelPrice] = {}
        for name, pair in (self._cfg.class_prices_rub_per_1k or {}).items():
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                out[name] = ModelPrice(
                    price_in_rub_per_1k=Decimal(str(pair[0])),
                    price_out_rub_per_1k=Decimal(str(pair[1])),
                )
        return out

    def _clamp_override(self, price: ModelPrice) -> ModelPrice:
        """Пер-модельная маржа не может быть ниже min_margin (защита от убытка)."""
        min_margin = self._min_margin()
        if price.margin_override is not None and price.margin_override < min_margin:
            return ModelPrice(price.price_in_rub_per_1k, price.price_out_rub_per_1k, min_margin)
        return price

    # --- основной расчёт -------------------------------------------------- #
    async def price_request(
        self,
        *,
        per_call_usage: list[dict[str, Any]] | None,
        tools: list[str] | None,
        is_complex: bool,
    ) -> PriceResult:
        registry = await self._repo.fetch_pricing_map()
        class_prices = self._class_prices()
        default_price = self._default_price()

        per_call_prices: list[tuple[int, int, ModelPrice]] = []
        for call in per_call_usage or []:
            price = resolve_model_price(
                call.get("model"),
                registry=registry,
                provider=call.get("provider"),
                classify=classify_model,
                class_prices=class_prices,
                default_price=default_price,
            )
            price = self._clamp_override(price)
            per_call_prices.append(
                (
                    int(call.get("prompt", 0) or 0),
                    int(call.get("completion", 0) or 0),
                    price,
                )
            )

        surcharges: list[Decimal] = []
        surcharge_map = self._cfg.tool_surcharge_rub or {}
        for tool in tools or []:
            value = surcharge_map.get(tool)
            if value:
                surcharges.append(Decimal(str(value)))

        return compute_credits(
            per_call_prices=per_call_prices,
            tool_surcharges_rub=surcharges,
            is_complex=bool(is_complex),
            params=self._params(),
        )
