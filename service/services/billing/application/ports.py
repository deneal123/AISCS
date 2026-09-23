"""Порты платежей: провайдер-агностичный контракт.

BillingService работает с нормализованным ``WebhookEvent`` независимо от
провайдера — каждая реализация ``PaymentProvider`` сама приводит свой формат
вебхука к этому виду. Кредиты НЕ берутся из вебхука: их сервер выводит из
plan/pack по конфигу (защита от подмены клиентом).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class CheckoutResult:
    redirect_url: str
    provider_ref: str
    # Для встраиваемых виджетов (напр. ЮKassa embedded) — токен инициализации.
    # У redirect-провайдеров остаётся None, фронт делает redirect по redirect_url.
    confirmation_token: str | None = None


@dataclass(frozen=True)
class WebhookEvent:
    id: str  # уникальный id события провайдера (ключ идемпотентности)
    type: str  # напр. "payment.succeeded"
    kind: str  # "subscription" | "topup"
    user_id: str
    amount_rub: float = 0.0
    plan: str | None = None  # для подписки
    pack_id: str | None = None  # для докупки
    currency: str = "RUB"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RefundEvent:
    """Нормализованный возврат платежа (authoritative — из ответа API провайдера).

    ``id`` — id возврата (ключ идемпотентности, отличен от payment_id);
    ``payment_id`` — исходный платёж, по нему находится начисление для отката.
    """

    id: str
    payment_id: str
    amount_rub: float = 0.0
    currency: str = "RUB"
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentWebhookError(Exception):
    """Невалидная подпись или тело вебхука → HTTP 400."""


@runtime_checkable
class PaymentProvider(Protocol):
    async def create_checkout(
        self,
        *,
        user_id: str,
        amount_rub: float,
        description: str,
        kind: str,
        metadata: dict[str, Any],
        customer_email: str | None = None,
    ) -> CheckoutResult: ...

    def verify_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> WebhookEvent: ...
