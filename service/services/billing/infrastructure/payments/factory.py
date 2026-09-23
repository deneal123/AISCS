"""Фабрика платёжного провайдера по конфигу (PAYMENTS__PROVIDER)."""

from __future__ import annotations

import logging
from typing import Any

from service.services.billing.application.ports import PaymentProvider
from service.services.billing.infrastructure.payments.mock_provider import MockPaymentProvider

logger = logging.getLogger(__name__)


def build_payment_provider(payments_config: Any) -> PaymentProvider:
    provider = (getattr(payments_config, "provider", "mock") or "mock").strip().lower()
    secret = getattr(payments_config, "webhook_secret", "") or ""

    if provider == "yookassa":
        from service.services.billing.infrastructure.payments.yookassa_provider import (
            YooKassaPaymentProvider,
        )

        shop_id = getattr(payments_config, "yookassa_shop_id", "") or ""
        secret_key = getattr(payments_config, "yookassa_secret_key", "") or ""
        if not shop_id or not secret_key:
            # Никакого тихого отката на mock: в проде это привело бы к фейковым
            # checkout-страницам без реального списания. Падаем явно, чтобы
            # оператор заметил незаполненные ключи ещё на старте.
            raise RuntimeError(
                "PAYMENTS__PROVIDER=yookassa, но не заданы "
                "PAYMENTS__YOOKASSA_SHOP_ID/PAYMENTS__YOOKASSA_SECRET_KEY. "
                "Заполните ключи боевого магазина ЮKassa или переключите провайдера на mock."
            )
        receipt_config = {
            "enabled": bool(getattr(payments_config, "receipt_enabled", False)),
            "vat_code": int(getattr(payments_config, "receipt_vat_code", 1) or 1),
            "payment_subject": getattr(payments_config, "receipt_payment_subject", "service"),
            "payment_mode": getattr(payments_config, "receipt_payment_mode", "full_payment"),
            "tax_system_code": int(getattr(payments_config, "receipt_tax_system_code", 0) or 0),
        }
        return YooKassaPaymentProvider(
            shop_id=shop_id, secret_key=secret_key, receipt_config=receipt_config
        )

    if provider != "mock":
        logger.warning("Unknown payment provider '%s'; falling back to mock", provider)

    # Mock БЕЗ секрета — открытый кран: verify_webhook пропускает проверку подписи
    # (mock_provider: `if self._secret:` ложно), и тело вебхука принимается на веру,
    # то есть любой неаутентифицированный POST на /api/billing/webhook начисляет
    # кредиты/подписку на произвольный user_id. Падаем на старте (как yookassa без
    # ключей), чтобы это нельзя было пронести в боевой запуск незамеченным. Для
    # локальной разработки достаточно задать любую строку в PAYMENTS__WEBHOOK_SECRET.
    if not secret:
        raise RuntimeError(
            "PAYMENTS__PROVIDER=mock, но PAYMENTS__WEBHOOK_SECRET пуст. Mock-провайдер "
            "без секрета принимает вебхуки без проверки подписи — любой POST на "
            "/api/billing/webhook начислит кредиты. Задайте PAYMENTS__WEBHOOK_SECRET "
            "(для разработки — любую непустую строку) или переключите провайдера на "
            "yookassa с боевыми ключами."
        )
    return MockPaymentProvider(webhook_secret=secret)
