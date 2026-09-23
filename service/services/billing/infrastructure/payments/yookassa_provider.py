"""Провайдер платежей ЮKassa (embedded-виджет) поверх PaymentProvider.

Флоу:
1. create_checkout → POST /v3/payments (confirmation: embedded, capture: true) →
   ЮKassa возвращает confirmation_token для инициализации виджета на фронте.
2. Пользователь платит в виджете → виджет редиректит на return_url.
3. ЮKassa шлёт webhook (event=payment.succeeded) → verify_webhook нормализует
   событие; handle_webhook (через confirm_succeeded) ПЕРЕПРОВЕРЯЕТ статус по API
   (защита от подделки уведомления) и начисляет кредиты (идемпотентно).

Кредиты НЕ берутся из платежа — сервер выводит их из plan/pack по конфигу.
Безопасность webhook: ЮKassa не подписывает уведомления секретом — рекомендуется
ограничить источник по IP ЮKassa на уровне reverse-proxy + перепроверка по API
(confirm_succeeded), что здесь и сделано.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any

import httpx

from service.services.billing.application.ports import (
    CheckoutResult,
    PaymentWebhookError,
    RefundEvent,
    WebhookEvent,
)

logger = logging.getLogger(__name__)

_API_BASE = "https://api.yookassa.ru/v3"


class YooKassaPaymentProvider:
    def __init__(
        self,
        *,
        shop_id: str,
        secret_key: str,
        receipt_config: dict[str, Any] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._shop_id = shop_id
        self._secret = secret_key
        # Реквизиты чека (54-ФЗ) из конфига платежей; None/пусто → чек не формируем.
        self._receipt_cfg = receipt_config or {}
        self._transport = transport  # для тестов (httpx.MockTransport)

    def _build_receipt(
        self, *, amount_rub: float, description: str, customer_email: str | None
    ) -> dict[str, Any] | None:
        """Собрать объект receipt для «Платёж и чек одновременно» (Чеки от ЮKassa).

        ЮKassa зарегистрирует фискальный чек и отправит его на customer.email. Без
        включённого receipt_enabled или без email чек не формируем (для Чеков от ЮKassa
        email обязателен) — платёж всё равно проходит, чек можно выставить вручную.
        """
        if not self._receipt_cfg.get("enabled"):
            return None
        email = (customer_email or "").strip()
        if not email:
            logger.warning("Receipt enabled, но нет email покупателя — чек не сформирован")
            return None
        item: dict[str, Any] = {
            "description": description[:128] or "Оплата услуг GPTHub",
            "quantity": "1.00",
            "amount": {"value": f"{float(amount_rub):.2f}", "currency": "RUB"},
            "vat_code": int(self._receipt_cfg.get("vat_code", 1) or 1),
            "payment_subject": str(self._receipt_cfg.get("payment_subject", "service")),
            "payment_mode": str(self._receipt_cfg.get("payment_mode", "full_payment")),
        }
        receipt: dict[str, Any] = {"customer": {"email": email}, "items": [item]}
        # tax_system_code — только для сторонних касс с несколькими СНО; для Чеков от
        # ЮKassa игнорируется. Передаём лишь при явно заданном (>0) значении.
        tax_code = int(self._receipt_cfg.get("tax_system_code", 0) or 0)
        if tax_code > 0:
            receipt["tax_system_code"] = tax_code
        return receipt

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=_API_BASE,
            auth=(self._shop_id, self._secret),
            transport=self._transport,
            timeout=30.0,
        )

    @staticmethod
    def _idempotence_key(kind: str, metadata: dict[str, Any]) -> str:
        """Стабильный ключ идемпотентности ЮKassa из (user, план/пак, 10-мин окно).

        Случайный uuid на каждый вызов не защищал от дабл-клика «Оплатить» —
        два клика создавали два платёжных черновика. Один и тот же запрос в
        пределах окна теперь схлопывается ЮKassa в один платёж; после окна
        пользователь может начать оплату заново. uuid — фолбэк, если по какой-то
        причине нет входных данных для ключа.
        """
        user_id = str(metadata.get("user_id") or "")
        target = str(metadata.get("plan") or metadata.get("pack_id") or "")
        if not user_id or not target:
            return uuid.uuid4().hex
        window = int(time.time() // 600)  # 10-минутное окно
        raw = f"{user_id}:{kind}:{target}:{window}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def create_checkout(
        self,
        *,
        user_id: str,
        amount_rub: float,
        description: str,
        kind: str,
        metadata: dict[str, Any],
        customer_email: str | None = None,
    ) -> CheckoutResult:
        body = {
            "amount": {"value": f"{float(amount_rub):.2f}", "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "embedded"},
            "description": description,
            "metadata": metadata,
        }
        # Данные чека (54-ФЗ) вместе с платежом → ЮKassa регистрирует фискальный чек и
        # сама шлёт его покупателю на customer.email («Платёж и чек одновременно»).
        receipt = self._build_receipt(
            amount_rub=amount_rub, description=description, customer_email=customer_email
        )
        if receipt:
            body["receipt"] = receipt
        async with self._client() as client:
            resp = await client.post(
                "/payments",
                json=body,
                headers={"Idempotence-Key": self._idempotence_key(kind, metadata)},
            )
        if resp.status_code >= 400:
            logger.error("YooKassa create payment failed: %s %s", resp.status_code, resp.text[:300])
            raise PaymentWebhookError("Не удалось создать платёж ЮKassa")
        data = resp.json()
        token = (data.get("confirmation") or {}).get("confirmation_token")
        if not token:
            raise PaymentWebhookError("ЮKassa не вернула confirmation_token")
        return CheckoutResult(
            redirect_url="", confirmation_token=str(token), provider_ref=str(data.get("id"))
        )

    def verify_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> WebhookEvent:
        try:
            body = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else str(raw_body)
            data = json.loads(body)
        except Exception as exc:
            raise PaymentWebhookError("Invalid YooKassa webhook body") from exc
        if not isinstance(data, dict):
            raise PaymentWebhookError("YooKassa webhook must be a JSON object")

        obj = data.get("object") or {}
        meta = obj.get("metadata") or {}
        amount = obj.get("amount") or {}
        payment_id = obj.get("id")
        if not payment_id:
            raise PaymentWebhookError("YooKassa webhook missing payment id")
        return WebhookEvent(
            id=str(payment_id),
            type=str(data.get("event", "")),  # напр. "payment.succeeded"
            kind=str(meta.get("kind", "")),
            user_id=str(meta.get("user_id", "")),
            plan=meta.get("plan"),
            pack_id=meta.get("pack_id"),
            amount_rub=float(amount.get("value", 0) or 0),
            currency=str(amount.get("currency", "RUB")),
            raw=data,
        )

    async def confirm_succeeded(self, payment_id: str) -> bool:
        """Перепроверить статус платежа по API (authoritative, анти-подделка)."""
        try:
            async with self._client() as client:
                resp = await client.get(f"/payments/{payment_id}")
            if resp.status_code >= 400:
                logger.warning("YooKassa fetch payment %s -> %s", payment_id, resp.status_code)
                return False
            return resp.json().get("status") == "succeeded"
        except Exception:
            logger.exception("YooKassa confirm_succeeded failed for %s", payment_id)
            return False

    async def fetch_authoritative_event(self, payment_id: str) -> WebhookEvent | None:
        """GET /payments/{id} и вывести событие ИЗ ОТВЕТА API, а не из тела вебхука.

        Тело POST /webhook ничем не подписано (ЮKassa не подписывает уведомления),
        поэтому доверять его metadata/amount нельзя — иначе атакующий может
        заменить kind/plan/pack_id/user_id/сумму в подделанном запросе для своего
        же реального payment_id и получить начисление, не совпадающее с оплатой.
        Возвращаем None, если платёж не найден или не succeeded.
        """
        try:
            async with self._client() as client:
                resp = await client.get(f"/payments/{payment_id}")
            if resp.status_code >= 400:
                logger.warning("YooKassa fetch payment %s -> %s", payment_id, resp.status_code)
                return None
            data = resp.json()
        except Exception:
            logger.exception("YooKassa fetch_authoritative_event failed for %s", payment_id)
            return None
        if data.get("status") != "succeeded":
            return None
        meta = data.get("metadata") or {}
        amount = data.get("amount") or {}
        return WebhookEvent(
            id=str(data.get("id") or payment_id),
            type="payment.succeeded",
            kind=str(meta.get("kind", "")),
            user_id=str(meta.get("user_id", "")),
            plan=meta.get("plan"),
            pack_id=meta.get("pack_id"),
            amount_rub=float(amount.get("value", 0) or 0),
            currency=str(amount.get("currency", "RUB")),
            raw=data,
        )

    async def fetch_authoritative_refund(self, refund_id: str) -> RefundEvent | None:
        """GET /refunds/{id} — authoritative-данные возврата (не из тела вебхука).

        Возврат ссылается на исходный платёж (``payment_id``), по которому потом
        находится начисление для отката. Как и с платежами, доверяем ТОЛЬКО ответу
        API: тело вебхука ничем не подписано. None, если возврат не найден или не
        ``succeeded``.
        """
        try:
            async with self._client() as client:
                resp = await client.get(f"/refunds/{refund_id}")
            if resp.status_code >= 400:
                logger.warning("YooKassa fetch refund %s -> %s", refund_id, resp.status_code)
                return None
            data = resp.json()
        except Exception:
            logger.exception("YooKassa fetch_authoritative_refund failed for %s", refund_id)
            return None
        if data.get("status") != "succeeded":
            return None
        amount = data.get("amount") or {}
        return RefundEvent(
            id=str(data.get("id") or refund_id),
            payment_id=str(data.get("payment_id") or ""),
            amount_rub=float(amount.get("value", 0) or 0),
            currency=str(amount.get("currency", "RUB")),
            raw=data,
        )
