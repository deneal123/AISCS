"""YooKassa-провайдер: create_checkout/verify_webhook/confirm_succeeded + factory."""

import json
from types import SimpleNamespace

import httpx
import pytest

from service.services.billing.application.billing_service import BillingService
from service.services.billing.application.ports import PaymentWebhookError
from service.services.billing.infrastructure.payments.factory import build_payment_provider
from service.services.billing.infrastructure.payments.yookassa_provider import (
    YooKassaPaymentProvider,
)


def _provider(handler):
    return YooKassaPaymentProvider(
        shop_id="shop", secret_key="key", transport=httpx.MockTransport(handler)
    )


def _provider_with_receipt(handler, **rc):
    cfg = {
        "enabled": True,
        "vat_code": 1,
        "payment_subject": "service",
        "payment_mode": "full_payment",
        "tax_system_code": 0,
    }
    cfg.update(rc)
    return YooKassaPaymentProvider(
        shop_id="shop", secret_key="key", receipt_config=cfg, transport=httpx.MockTransport(handler)
    )


def _capture_body_handler(captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "p", "confirmation": {"confirmation_token": "ct"}})

    return handler


@pytest.mark.asyncio
async def test_create_checkout_builds_embedded_payment():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["idem"] = request.headers.get("Idempotence-Key")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "pay_1",
                "status": "pending",
                "confirmation": {"type": "embedded", "confirmation_token": "ct-xyz"},
            },
        )

    provider = _provider(handler)
    result = await provider.create_checkout(
        user_id="u1",
        amount_rub=990,
        description="Подписка pro",
        kind="subscription",
        metadata={"kind": "subscription", "plan": "pro", "user_id": "u1"},
    )

    assert result.confirmation_token == "ct-xyz"
    assert result.provider_ref == "pay_1"
    assert captured["method"] == "POST" and captured["path"].endswith("/payments")
    assert captured["idem"]  # идемпотентность
    assert captured["body"]["confirmation"] == {"type": "embedded"}
    assert captured["body"]["capture"] is True
    assert captured["body"]["amount"] == {"value": "990.00", "currency": "RUB"}
    assert captured["body"]["metadata"]["plan"] == "pro"


@pytest.mark.asyncio
async def test_idempotence_key_stable_within_window():
    # Дабл-клик «Оплатить» одного юзера по одному тарифу в пределах окна должен
    # дать ОДИН и тот же Idempotence-Key (ЮKassa схлопнет в один платёж).
    keys = []

    def handler(request: httpx.Request) -> httpx.Response:
        keys.append(request.headers.get("Idempotence-Key"))
        return httpx.Response(
            200,
            json={"id": "p", "confirmation": {"confirmation_token": "ct"}},
        )

    provider = _provider(handler)
    meta = {"kind": "subscription", "plan": "pro", "user_id": "u1"}
    for _ in range(2):
        await provider.create_checkout(
            user_id="u1", amount_rub=990, description="d", kind="subscription", metadata=meta
        )
    assert keys[0] == keys[1]
    # Другой тариф того же юзера — другой ключ.
    await provider.create_checkout(
        user_id="u1",
        amount_rub=299,
        description="d",
        kind="topup",
        metadata={"kind": "topup", "pack_id": "p100k", "user_id": "u1"},
    )
    assert keys[2] != keys[0]


@pytest.mark.asyncio
async def test_create_checkout_api_error_raises():
    provider = _provider(lambda req: httpx.Response(400, json={"description": "bad"}))
    with pytest.raises(PaymentWebhookError):
        await provider.create_checkout(
            user_id="u1", amount_rub=10, description="x", kind="topup", metadata={}
        )


def test_verify_webhook_parses_notification():
    provider = _provider(lambda req: httpx.Response(200))
    body = json.dumps(
        {
            "event": "payment.succeeded",
            "object": {
                "id": "pay_2",
                "status": "succeeded",
                "amount": {"value": "299.00", "currency": "RUB"},
                "metadata": {"kind": "topup", "pack_id": "p100k", "user_id": "u1"},
            },
        }
    ).encode()
    event = provider.verify_webhook(raw_body=body, headers={})
    assert event.id == "pay_2"
    assert event.type == "payment.succeeded"
    assert event.kind == "topup"
    assert event.pack_id == "p100k"
    assert event.user_id == "u1"
    assert event.amount_rub == 299.0


def test_verify_webhook_bad_body():
    provider = _provider(lambda req: httpx.Response(200))
    with pytest.raises(PaymentWebhookError):
        provider.verify_webhook(raw_body=b"not-json", headers={})


@pytest.mark.asyncio
async def test_confirm_succeeded():
    def handler(request: httpx.Request) -> httpx.Response:
        status = "succeeded" if request.url.path.endswith("/pay_ok") else "pending"
        return httpx.Response(200, json={"id": "x", "status": status})

    provider = _provider(handler)
    assert await provider.confirm_succeeded("pay_ok") is True
    assert await provider.confirm_succeeded("pay_pending") is False


def test_factory_builds_yookassa_when_configured():
    cfg = SimpleNamespace(
        provider="yookassa", webhook_secret="", yookassa_shop_id="s", yookassa_secret_key="k"
    )
    assert isinstance(build_payment_provider(cfg), YooKassaPaymentProvider)


def test_factory_raises_when_yookassa_unconfigured():
    # Тихий откат на mock недопустим: провайдер=yookassa без ключей → явная ошибка.
    cfg = SimpleNamespace(
        provider="yookassa", webhook_secret="", yookassa_shop_id="", yookassa_secret_key=""
    )
    with pytest.raises(RuntimeError):
        build_payment_provider(cfg)


# --- handle_webhook с перепроверкой статуса ---------------------------------- #
class _FakeRepo:
    def __init__(self):
        self.applied = []

    async def apply_webhook(self, **kwargs):
        self.applied.append(kwargs)
        return {"status": "ok"}


class _ProviderWithConfirm:
    def __init__(self, confirmed: bool):
        self._confirmed = confirmed

    def verify_webhook(self, *, raw_body, headers):
        from service.services.billing.application.ports import WebhookEvent

        return WebhookEvent(
            id="pay_1", type="payment.succeeded", kind="subscription", user_id="u1", plan="pro"
        )

    async def confirm_succeeded(self, payment_id):
        return self._confirmed


def _cfg():
    return SimpleNamespace(
        plan_credits={"pro": 500000}, plan_prices_rub={"pro": 990}, topup_packs=[]
    )


@pytest.mark.asyncio
async def test_handle_webhook_applies_when_confirmed():
    repo = _FakeRepo()
    svc = BillingService(repo, _cfg(), payment_provider=_ProviderWithConfirm(True))
    res = await svc.handle_webhook(raw_body=b"{}", headers={})
    assert res["status"] == "ok"
    assert repo.applied[0]["grant"]["credits"] == 500000


@pytest.mark.asyncio
async def test_handle_webhook_rejects_when_not_confirmed():
    repo = _FakeRepo()
    svc = BillingService(repo, _cfg(), payment_provider=_ProviderWithConfirm(False))
    res = await svc.handle_webhook(raw_body=b"{}", headers={})
    assert res["status"] == "unconfirmed"
    assert repo.applied == []  # ничего не начислено


# --- фискальный чек (54-ФЗ) в платеже --------------------------------------- #
@pytest.mark.asyncio
async def test_receipt_attached_when_enabled():
    captured = {}
    provider = _provider_with_receipt(_capture_body_handler(captured), vat_code=4)
    await provider.create_checkout(
        user_id="u1",
        amount_rub=990,
        description="Подписка pro",
        kind="subscription",
        metadata={},
        customer_email="user@ex.ru",
    )
    receipt = captured["body"]["receipt"]
    assert receipt["customer"]["email"] == "user@ex.ru"
    item = receipt["items"][0]
    assert item["amount"] == {"value": "990.00", "currency": "RUB"}
    assert item["vat_code"] == 4
    assert item["payment_subject"] == "service"
    assert item["payment_mode"] == "full_payment"
    assert item["quantity"] == "1.00"
    assert "tax_system_code" not in receipt  # 0 → не передаём (Чеки от ЮKassa игнорируют)


@pytest.mark.asyncio
async def test_no_receipt_when_disabled():
    captured = {}
    provider = _provider(_capture_body_handler(captured))  # без receipt_config
    await provider.create_checkout(
        user_id="u1",
        amount_rub=990,
        description="d",
        kind="subscription",
        metadata={},
        customer_email="user@ex.ru",
    )
    assert "receipt" not in captured["body"]


@pytest.mark.asyncio
async def test_no_receipt_without_email():
    # Для Чеков от ЮKassa email обязателен: без него чек не формируем, платёж проходит.
    captured = {}
    provider = _provider_with_receipt(_capture_body_handler(captured))
    await provider.create_checkout(
        user_id="u1",
        amount_rub=990,
        description="d",
        kind="subscription",
        metadata={},
        customer_email=None,
    )
    assert "receipt" not in captured["body"]


@pytest.mark.asyncio
async def test_receipt_includes_tax_system_code_when_set():
    captured = {}
    provider = _provider_with_receipt(_capture_body_handler(captured), tax_system_code=2)
    await provider.create_checkout(
        user_id="u1",
        amount_rub=10,
        description="d",
        kind="topup",
        metadata={},
        customer_email="user@ex.ru",
    )
    assert captured["body"]["receipt"]["tax_system_code"] == 2


# --- брендовое письмо об оплате (транзакционное, идемпотентное) --------------- #
class _RepoWithEmail(_FakeRepo):
    def __init__(self, status="ok"):
        super().__init__()
        self._status = status

    async def apply_webhook(self, **kwargs):
        self.applied.append(kwargs)
        return {"status": self._status, "kind": "subscription", "credits": 500000}

    async def get_user_email(self, *, user_id):
        return "buyer@ex.ru"


def _patch_email_task(monkeypatch, sink):
    class _Task:
        def delay(self, to, credits, amount_rub, plan):
            sink["args"] = (to, credits, amount_rub, plan)

    from service.infrastructure.messaging import tasks as real_tasks

    monkeypatch.setattr(real_tasks, "send_payment_receipt_email", _Task())


@pytest.mark.asyncio
async def test_new_payment_enqueues_branded_email(monkeypatch):
    sink = {}
    _patch_email_task(monkeypatch, sink)
    svc = BillingService(_RepoWithEmail("ok"), _cfg(), payment_provider=_ProviderWithConfirm(True))
    await svc.handle_webhook(raw_body=b"{}", headers={})
    assert sink["args"] == ("buyer@ex.ru", 500000, 990.0, "pro")


@pytest.mark.asyncio
async def test_duplicate_webhook_does_not_resend_email(monkeypatch):
    # Повтор вебхука (already_processed) не должен дублировать письмо покупателю.
    sink = {}
    _patch_email_task(monkeypatch, sink)
    svc = BillingService(
        _RepoWithEmail("already_processed"), _cfg(), payment_provider=_ProviderWithConfirm(True)
    )
    await svc.handle_webhook(raw_body=b"{}", headers={})
    assert "args" not in sink
