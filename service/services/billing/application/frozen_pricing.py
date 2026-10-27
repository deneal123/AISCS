"""Serializable tariff snapshot using the existing billing formula and resolver."""

from dataclasses import replace
from decimal import Decimal

from pydantic import Field, field_validator

from service.services.billing.application.pricing_service import PricingService, classify_model
from service.services.billing.domain.pricing import (
    ModelPrice,
    PricingParams,
    compute_credits,
    resolve_model_price,
)
from service.shared.model_class import is_free_local_model
from service.shared.task_contract import ContractModel, digest_payload, immutable_items


class TariffEntry(ContractModel):
    model: str
    provider: str | None = None
    incoming: str
    outgoing: str
    margin: str | None = None

    def price(self):
        values = [Decimal(self.incoming), Decimal(self.outgoing)]
        if self.margin is not None:
            values.append(Decimal(self.margin))
        if any(not value.is_finite() or value < 0 for value in values):
            raise ValueError("tariff_invalid")
        return ModelPrice(values[0], values[1], values[2] if len(values) == 3 else None)


class FrozenPricing(ContractModel):
    entries: tuple[TariffEntry, ...] = Field(max_length=10000)
    classes: tuple[TariffEntry, ...] = Field(max_length=64)
    default: TariffEntry
    credit_unit: str
    margin: str
    complexity: str
    minimum: int = Field(ge=0)
    minimum_margin: str
    surcharges: dict[str, str]

    _items = field_validator("entries", "classes", mode="before")(immutable_items)

    @property
    def digest(self):
        return digest_payload(self.model_dump(mode="json"))

    def price(self, calls, tools=(), *, complex=False):
        registry = {
            (item.provider, item.model) if item.provider else item.model: item.price()
            for item in self.entries
        }
        classes = {item.model: item.price() for item in self.classes}
        prices = []
        for call in calls:
            price = resolve_model_price(
                call.get("model"),
                provider=call.get("provider"),
                registry=registry,
                classify=classify_model,
                class_prices=classes,
                default_price=self.default.price(),
            )
            if price.margin_override is not None:
                price = ModelPrice(
                    price.price_in_rub_per_1k,
                    price.price_out_rub_per_1k,
                    max(price.margin_override, Decimal(self.minimum_margin)),
                    price.is_free,
                )
            prices.append((call.get("prompt", 0), call.get("completion", 0), price))
        return compute_credits(
            per_call_prices=prices,
            tool_surcharges_rub=[
                Decimal(self.surcharges[name]) for name in set(tools) if name in self.surcharges
            ],
            is_complex=complex,
            params=PricingParams(
                Decimal(self.credit_unit),
                Decimal(self.margin),
                Decimal(self.complexity),
                self.minimum,
            ),
        )

    def task_price(self, calls, tools=(), *, selected_model=None):
        actual = self.price(calls, tools)
        if not selected_model or is_free_local_model(selected_model):
            return actual
        selected = self.price(
            [{**call, "model": selected_model, "provider": None} for call in calls], tools
        )
        if selected.credits < actual.credits:
            return replace(selected, raw_cost_rub=actual.raw_cost_rub)
        return actual


def _entry(key, value):
    provider, model = key if isinstance(key, tuple) else (None, key)
    return TariffEntry(
        provider=provider,
        model=model,
        incoming=str(value.price_in_rub_per_1k),
        outgoing=str(value.price_out_rub_per_1k),
        margin=str(value.margin_override) if value.margin_override is not None else None,
    )


async def freeze_pricing(service: PricingService) -> FrozenPricing:
    params = service._params()
    return FrozenPricing(
        entries=[
            _entry(key, value) for key, value in (await service._repo.fetch_pricing_map()).items()
        ],
        classes=[_entry(key, value) for key, value in service._class_prices().items()],
        default=_entry("default", service._default_price()),
        credit_unit=str(params.credit_unit_rub),
        margin=str(params.margin_multiplier),
        complexity=str(params.complexity_factor_complex),
        minimum=params.min_credits_per_request,
        minimum_margin=str(service._min_margin()),
        surcharges={
            name: str(value) for name, value in (service._cfg.tool_surcharge_rub or {}).items()
        },
    )
