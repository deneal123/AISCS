"""Фаза 4 биллинга: платежи (провайдер-агностик) — mock-провайдер, checkout,
идемпотентный webhook, провижининг подписки/докупки, роутер.
"""

import json
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from service.services.billing.application.billing_service import BillingService
from service.services.billing.application.ports import PaymentWebhookError
from service.services.billing.infrastructure.payments.factory import build_payment_provider
from service.services.billing.infrastructure.payments.mock_provider import MockPaymentProvider
from service.services.billing.persistence.billing_repository import BillingRepository
from tests.test_helpers import FakeConnector, FakeDBSession


def _cfg(**overrides):
    base = dict(
        free_plan_credits=10_000,
        plan_credits={"free": 10_000, "pro": 500_000},
        plan_prices_rub={"free": 0, "pro": 990},
        topup_packs=[{"id": "p100k", "credits": 100_000, "price_rub": 299}],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
# MockPaymentProvider                                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_mock_provider_create_checkout() -> None:
    provider = MockPaymentProvider()
    result = await provider.create_checkout(
        user_id="u1", amount_rub=990, description="Подписка pro", kind="subscription", metadata={}
    )
    assert result.redirect_url.startswith("https://mock-pay.local/checkout/")
    assert result.provider_ref


def test_mock_provider_verify_webhook_parses() -> None:
    provider = MockPaymentProvider()
    body = json.dumps(
        {
            "id": "evt1",
            "type": "payment.succeeded",
            "kind": "subscription",
            "user_id": "u1",
            "plan": "pro",
        }
    ).encode()
    event = provider.verify_webhook(raw_body=body, headers={})
    assert event.id == "evt1"
    assert event.kind == "subscription"
    assert event.plan == "pro"


def test_mock_provider_bad_signature() -> None:
    provider = MockPaymentProvider(webhook_secret="s3cret")
    with pytest.raises(PaymentWebhookError):
        provider.verify_webhook(raw_body=b"{}", headers={"x-mock-signature": "wrong"})


def test_mock_provider_bad_body() -> None:
    provider = MockPaymentProvider()
    with pytest.raises(PaymentWebhookError):
        provider.verify_webhook(raw_body=b"not-json", headers={})


def test_mock_provider_missing_fields() -> None:
    provider = MockPaymentProvider()
    with pytest.raises(PaymentWebhookError):
        provider.verify_webhook(raw_body=json.dumps({"id": "e"}).encode(), headers={})


def test_factory_raises_for_yookassa_without_keys() -> None:
    # provider=yookassa без ключей → явная ошибка (никакого тихого mock).
    with pytest.raises(RuntimeError):
        build_payment_provider(SimpleNamespace(provider="yookassa", webhook_secret=""))


def test_factory_returns_mock_for_unknown_provider() -> None:
    provider = build_payment_provider(
        SimpleNamespace(provider="totally-unknown", webhook_secret="s")
    )
    assert isinstance(provider, MockPaymentProvider)


def test_factory_raises_for_mock_without_secret() -> None:
    # mock без секрета — открытый кран (вебхуки без проверки подписи). Падаем на
    # старте, чтобы это нельзя было пронести в прод незамеченным.
    with pytest.raises(RuntimeError):
        build_payment_provider(SimpleNamespace(provider="mock", webhook_secret=""))


def test_factory_returns_mock_with_secret() -> None:
    provider = build_payment_provider(SimpleNamespace(provider="mock", webhook_secret="s3cret"))
    assert isinstance(provider, MockPaymentProvider)


# --------------------------------------------------------------------------- #
# BillingService.create_checkout                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_create_checkout_subscription() -> None:
    svc = BillingService(object(), _cfg(), payment_provider=MockPaymentProvider())
    result = await svc.create_checkout(user_id="u1", kind="subscription", plan="pro")
    assert result["checkout_url"].startswith("https://mock-pay.local/checkout/")
    assert result["confirmation_token"] is None


@pytest.mark.asyncio
async def test_create_checkout_unknown_plan_raises() -> None:
    svc = BillingService(object(), _cfg(), payment_provider=MockPaymentProvider())
    with pytest.raises(ValueError):
        await svc.create_checkout(user_id="u1", kind="subscription", plan="ghost")


@pytest.mark.asyncio
async def test_create_checkout_topup_unknown_pack_raises() -> None:
    svc = BillingService(object(), _cfg(), payment_provider=MockPaymentProvider())
    with pytest.raises(ValueError):
        await svc.create_checkout(user_id="u1", kind="topup", pack_id="ghost")


@pytest.mark.asyncio
async def test_create_checkout_free_plan_raises() -> None:
    # Бесплатный тариф (цена 0) нельзя оформить через оплату — иначе 500 от ЮKassa.
    svc = BillingService(object(), _cfg(), payment_provider=MockPaymentProvider())
    with pytest.raises(ValueError):
        await svc.create_checkout(user_id="u1", kind="subscription", plan="free")


@pytest.mark.asyncio
async def test_create_checkout_no_provider_raises() -> None:
    svc = BillingService(object(), _cfg(), payment_provider=None)
    with pytest.raises(PaymentWebhookError):
        await svc.create_checkout(user_id="u1", kind="subscription", plan="pro")


# --------------------------------------------------------------------------- #
# BillingService.handle_webhook — credits derived from config (anti-spoof)    #
# --------------------------------------------------------------------------- #
class _FakeRepo:
    def __init__(self):
        self.apply_calls = []

    async def apply_webhook(self, **kwargs):
        self.apply_calls.append(kwargs)
        return {"status": "ok", "kind": kwargs["grant"].get("kind")}


def _svc_with_repo():
    repo = _FakeRepo()
    return BillingService(repo, _cfg(), payment_provider=MockPaymentProvider()), repo


@pytest.mark.asyncio
async def test_handle_webhook_subscription_uses_config_credits() -> None:
    svc, repo = _svc_with_repo()
    body = json.dumps(
        {
            "id": "evt1",
            "type": "payment.succeeded",
            "kind": "subscription",
            "user_id": "u1",
            "plan": "pro",
            "credits": 999999,  # клиент врёт — должно игнорироваться
        }
    ).encode()
    res = await svc.handle_webhook(raw_body=body, headers={}, today=date(2026, 6, 26))
    assert res["status"] == "ok"
    grant = repo.apply_calls[0]["grant"]
    assert grant["credits"] == 500_000  # из конфига plan_credits["pro"], не из тела
    # Период подписки — скользящие N дней, не календарный месяц.
    assert repo.apply_calls[0]["period_days"] == 30


@pytest.mark.asyncio
async def test_handle_webhook_topup_uses_pack_credits() -> None:
    svc, repo = _svc_with_repo()
    body = json.dumps(
        {
            "id": "evt2",
            "type": "payment.succeeded",
            "kind": "topup",
            "user_id": "u1",
            "pack_id": "p100k",
        }
    ).encode()
    res = await svc.handle_webhook(raw_body=body, headers={}, today=date(2026, 6, 26))
    assert res["status"] == "ok"
    assert repo.apply_calls[0]["grant"]["credits"] == 100_000


@pytest.mark.asyncio
async def test_handle_webhook_ignores_unknown_plan() -> None:
    svc, repo = _svc_with_repo()
    body = json.dumps(
        {
            "id": "evt3",
            "type": "payment.succeeded",
            "kind": "subscription",
            "user_id": "u1",
            "plan": "ghost",
        }
    ).encode()
    res = await svc.handle_webhook(raw_body=body, headers={})
    assert res["status"] == "ignored"
    assert repo.apply_calls == []


@pytest.mark.asyncio
async def test_handle_webhook_ignores_non_success_type() -> None:
    svc, repo = _svc_with_repo()
    body = json.dumps(
        {
            "id": "evt4",
            "type": "payment.pending",
            "kind": "subscription",
            "user_id": "u1",
            "plan": "pro",
        }
    ).encode()
    res = await svc.handle_webhook(raw_body=body, headers={})
    assert res["status"] == "ignored"
    assert repo.apply_calls == []


# --------------------------------------------------------------------------- #
# BillingRepository.apply_webhook — атомарность/идемпотентность               #
# --------------------------------------------------------------------------- #
def _find(executed, needle):
    return [(s, p) for s, p in executed if needle in s]


@pytest.mark.asyncio
async def test_repo_apply_webhook_subscription_first_time() -> None:
    session = FakeDBSession()  # вебхука нет → exists None
    repo = BillingRepository(FakeConnector(session))
    res = await repo.apply_webhook(
        webhook_id="evt1",
        event_type="payment.succeeded",
        payload={"id": "evt1"},
        user_id="u1",
        grant={
            "kind": "subscription",
            "plan": "pro",
            "credits": 500_000,
            "amount_rub": 990,
            "currency": "RUB",
        },
    )
    assert res["status"] == "ok"
    assert _find(session.executed, "INSERT INTO profile.token_quotas")
    assert _find(session.executed, "UPDATE profile.user SET plan")
    assert _find(session.executed, "INSERT INTO profile.billing_events")
    assert _find(session.executed, "INSERT INTO profile.billing_webhooks")
    assert session._committed is True


@pytest.mark.asyncio
async def test_repo_apply_webhook_topup_first_time() -> None:
    session = FakeDBSession()
    repo = BillingRepository(FakeConnector(session))
    res = await repo.apply_webhook(
        webhook_id="evt2",
        event_type="payment.succeeded",
        payload={},
        user_id="u1",
        grant={
            "kind": "topup",
            "pack_id": "p100k",
            "credits": 100_000,
            "amount_rub": 299,
            "currency": "RUB",
        },
    )
    assert res["status"] == "ok"
    assert _find(session.executed, "topup_credit_balance = topup_credit_balance +")
    assert _find(session.executed, "INSERT INTO profile.billing_webhooks")


@pytest.mark.asyncio
async def test_repo_apply_webhook_idempotent() -> None:
    # вебхук уже есть → already_processed, никаких начислений
    session = FakeDBSession(first_map={"FROM profile.billing_webhooks WHERE webhook_id": (1,)})
    repo = BillingRepository(FakeConnector(session))
    res = await repo.apply_webhook(
        webhook_id="evt1",
        event_type="payment.succeeded",
        payload={},
        user_id="u1",
        grant={"kind": "subscription", "plan": "pro", "credits": 500_000},
    )
    assert res["status"] == "already_processed"
    assert _find(session.executed, "INSERT INTO profile.token_quotas") == []
    assert _find(session.executed, "INSERT INTO profile.billing_webhooks") == []


@pytest.mark.asyncio
async def test_repo_apply_refund_topup_clawback() -> None:
    # начисление topup 100k за платёж pay1 → полный возврат откатывает все 100k.
    session = FakeDBSession(
        first_map={
            "metadata->>'payment_id' = :pid": ("u1", "topup", 299.0, 100_000),
        }
    )
    repo = BillingRepository(FakeConnector(session))
    res = await repo.apply_refund(
        refund_id="ref1",
        source_payment_id="pay1",
        event_type="refund.succeeded",
        payload={},
        amount_rub=299.0,
    )
    assert res["status"] == "ok"
    assert res["clawback"] == 100_000
    assert _find(session.executed, "topup_credit_balance = GREATEST(0, topup_credit_balance -")
    assert _find(session.executed, "INSERT INTO profile.billing_events")
    assert _find(session.executed, "INSERT INTO profile.billing_webhooks")


@pytest.mark.asyncio
async def test_repo_apply_refund_partial_proportional() -> None:
    # частичный возврат 150 из 300 при начислении 100k → clawback 50k.
    session = FakeDBSession(
        first_map={"metadata->>'payment_id' = :pid": ("u1", "topup", 300.0, 100_000)}
    )
    repo = BillingRepository(FakeConnector(session))
    res = await repo.apply_refund(
        refund_id="ref2",
        source_payment_id="pay2",
        event_type="refund.succeeded",
        payload={},
        amount_rub=150.0,
    )
    assert res["clawback"] == 50_000


@pytest.mark.asyncio
async def test_repo_apply_refund_idempotent() -> None:
    session = FakeDBSession(first_map={"FROM profile.billing_webhooks WHERE webhook_id": (1,)})
    repo = BillingRepository(FakeConnector(session))
    res = await repo.apply_refund(
        refund_id="ref1",
        source_payment_id="pay1",
        event_type="refund.succeeded",
        payload={},
        amount_rub=299.0,
    )
    assert res["status"] == "already_processed"
    assert _find(session.executed, "INSERT INTO profile.billing_events") == []


@pytest.mark.asyncio
async def test_repo_apply_refund_no_grant() -> None:
    # платёж без известного начисления → вебхук всё равно отмечается (не ретраить).
    session = FakeDBSession()
    repo = BillingRepository(FakeConnector(session))
    res = await repo.apply_refund(
        refund_id="ref3",
        source_payment_id="unknown-pay",
        event_type="refund.succeeded",
        payload={},
        amount_rub=100.0,
    )
    assert res["status"] == "no_grant"
    assert res["clawback"] == 0
    assert _find(session.executed, "INSERT INTO profile.billing_webhooks")


@pytest.mark.asyncio
async def test_reconcile_unsupported_for_mock() -> None:
    # mock-провайдер без authoritative-fetch → сверять нечем, no-op.
    svc = BillingService(_FakeRepo(), _cfg(), payment_provider=MockPaymentProvider())
    res = await svc.reconcile_pending_payments()
    assert res["status"] == "unsupported"


@pytest.mark.asyncio
async def test_reconcile_recovers_lost_payment() -> None:
    # Провайдер подтверждает succeeded по API; вебхук не приходил → сверка начисляет.
    from types import SimpleNamespace

    class _ReconRepo:
        def __init__(self):
            self.applied = []
            self.statuses = []

        async def fetch_stale_pending_payments(self, **kwargs):
            return [
                {
                    "payment_id": "pay1",
                    "user_id": "u1",
                    "kind": "topup",
                    "plan": None,
                    "pack_id": "p100k",
                }
            ]

        async def apply_webhook(self, **kwargs):
            self.applied.append(kwargs)
            return {"status": "ok"}

        async def set_payment_status(self, **kwargs):
            self.statuses.append(kwargs)

    class _AuthProvider:
        async def fetch_authoritative_event(self, payment_id):
            return SimpleNamespace(
                id=payment_id,
                type="payment.succeeded",
                kind="topup",
                user_id="u1",
                plan=None,
                pack_id="p100k",
                amount_rub=299,
                currency="RUB",
                raw={},
            )

    repo = _ReconRepo()
    svc = BillingService(repo, _cfg(), payment_provider=_AuthProvider())
    res = await svc.reconcile_pending_payments()
    assert res["reconciled"] == 1
    assert repo.applied[0]["grant"]["credits"] == 100_000  # из конфига
    assert repo.statuses[0] == {"payment_id": "pay1", "status": "reconciled"}


@pytest.mark.asyncio
async def test_reconcile_skips_unconfirmed() -> None:
    # Платёж ещё не succeeded (fetch вернул None) → статус не трогаем, не начисляем.
    class _ReconRepo:
        def __init__(self):
            self.applied = []
            self.statuses = []

        async def fetch_stale_pending_payments(self, **kwargs):
            return [
                {
                    "payment_id": "pay1",
                    "user_id": "u1",
                    "kind": "topup",
                    "plan": None,
                    "pack_id": "p100k",
                }
            ]

        async def apply_webhook(self, **kwargs):
            self.applied.append(kwargs)
            return {"status": "ok"}

        async def set_payment_status(self, **kwargs):
            self.statuses.append(kwargs)

    class _PendingProvider:
        async def fetch_authoritative_event(self, payment_id):
            return None  # ещё pending/canceled

    repo = _ReconRepo()
    svc = BillingService(repo, _cfg(), payment_provider=_PendingProvider())
    res = await svc.reconcile_pending_payments()
    assert res["reconciled"] == 0
    assert repo.applied == []
    assert repo.statuses == []


@pytest.mark.asyncio
async def test_handle_webhook_refund_from_body_mock() -> None:
    # mock-провайдер (без authoritative-refund): payment_id из тела вебхука.
    class _RefundRepo:
        def __init__(self):
            self.calls = []

        async def apply_refund(self, **kwargs):
            self.calls.append(kwargs)
            return {"status": "ok", "clawback": 100_000}

    repo = _RefundRepo()
    svc = BillingService(repo, _cfg(), payment_provider=MockPaymentProvider())
    body = json.dumps(
        {"id": "ref1", "type": "refund.succeeded", "payment_id": "pay1", "amount_rub": 299}
    ).encode()
    res = await svc.handle_webhook(raw_body=body, headers={})
    assert res["status"] == "ok"
    assert repo.calls[0]["source_payment_id"] == "pay1"
    assert repo.calls[0]["refund_id"] == "ref1"


# --------------------------------------------------------------------------- #
# Router smoke (TestClient + dependency overrides)                            #
# --------------------------------------------------------------------------- #
class _RouterRepo:
    async def get_balance(self, *, user_id):
        return {
            "plan": "free",
            "topup": 200,
            "limit": 10000,
            "used": 3000,
            "period_end": date(2026, 7, 1),
        }

    async def apply_webhook(self, **kwargs):
        return {"status": "ok"}


def test_billing_router_balance_packs_and_webhook() -> None:
    from service.composition.state import get_billing_service
    from service.main import app
    from service.models.auth_models import AuthProfile
    from service.models.key_value import UserTypes
    from service.shared.security.auth_checker import check_auth

    svc = BillingService(_RouterRepo(), _cfg(), payment_provider=MockPaymentProvider())

    app.dependency_overrides[check_auth] = lambda: AuthProfile(
        user_id="00000000-0000-0000-0000-000000000000", fingerprint=None, type=UserTypes.REGISTERED
    )
    app.dependency_overrides[get_billing_service] = lambda: svc
    try:
        client = TestClient(app)

        balance = client.get("/api/billing/balance")
        assert balance.status_code == 200
        assert balance.json()["total"] == 7200

        packs = client.get("/api/billing/packs")
        assert packs.status_code == 200
        assert any(p["id"] == "pro" for p in packs.json()["plans"])

        checkout = client.post(
            "/api/billing/checkout", json={"kind": "subscription", "plan": "pro"}
        )
        assert checkout.status_code == 200
        assert checkout.json()["checkout_url"].startswith("https://")

        bad = client.post("/api/billing/checkout", json={"kind": "subscription", "plan": "ghost"})
        assert bad.status_code == 400

        webhook = client.post(
            "/api/billing/webhook",
            content=json.dumps(
                {
                    "id": "evt9",
                    "type": "payment.succeeded",
                    "kind": "topup",
                    "user_id": "u1",
                    "pack_id": "p100k",
                }
            ),
        )
        assert webhook.status_code == 200
        assert webhook.json()["status"] == "ok"
    finally:
        app.dependency_overrides.pop(check_auth, None)
        app.dependency_overrides.pop(get_billing_service, None)
