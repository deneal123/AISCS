"""Mock-провайдер платежей для разработки и тестов.

``create_checkout`` сразу выдаёт URL «оплаты» (реального списания нет). Вебхук
эмулируется фронтом/тестом POST-запросом на /api/billing/webhook с телом
события. Подпись — простой общий секрет в заголовке X-Mock-Signature.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from service.services.billing.application.ports import (
    CheckoutResult,
    PaymentWebhookError,
    WebhookEvent,
)


class MockPaymentProvider:
    def __init__(self, *, webhook_secret: str = "") -> None:
        self._secret = webhook_secret

    async def create_checkout(
        self,
        *,
        user_id: str,
        amount_rub: float,
        description: str,
        kind: str,
        metadata: dict[str, Any],
        customer_email: str | None = None,  # игнорируем: mock не фискализирует
    ) -> CheckoutResult:
        ref = uuid.uuid4().hex
        url = f"https://mock-pay.local/checkout/{ref}?amount={amount_rub}&kind={kind}"
        return CheckoutResult(redirect_url=url, provider_ref=ref)

    def verify_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> WebhookEvent:
        if self._secret:
            signature = headers.get("x-mock-signature") or headers.get("X-Mock-Signature")
            if signature != self._secret:
                raise PaymentWebhookError("Invalid mock signature")
        try:
            body = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else str(raw_body)
            data = json.loads(body)
        except Exception as exc:
            raise PaymentWebhookError("Invalid webhook body") from exc
        if not isinstance(data, dict):
            raise PaymentWebhookError("Webhook body must be a JSON object")
        event_type = str(data.get("type", "payment.succeeded"))
        try:
            # Для возврата kind/user_id не нужны — их выведет apply_refund по
            # payment_id из тела (в yookassa-режиме — по authoritative API).
            is_refund = event_type.startswith("refund.")
            return WebhookEvent(
                id=str(data["id"]),
                type=event_type,
                kind=str(data.get("kind", "")) if is_refund else str(data["kind"]),
                user_id=str(data.get("user_id", "")) if is_refund else str(data["user_id"]),
                amount_rub=float(data.get("amount_rub", 0) or 0),
                plan=data.get("plan"),
                pack_id=data.get("pack_id"),
                currency=str(data.get("currency", "RUB")),
                raw=data,
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise PaymentWebhookError("Malformed webhook event") from exc
