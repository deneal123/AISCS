"""Периодические задачи обязаны говорить правду о том, что сделали.

🔴 ПОЧЕМУ ЭТО ВАЖНЕЕ, ЧЕМ ВЫГЛЯДИТ. Каждая задача здесь ГЛОТАЕТ любое исключение и
возвращает `{"status": "error"}`. Для Celery это УСПЕХ: ни повтора, ни сигнала — просто
словарь, который никто не читает. Значит вечно падающая периодическая задача выглядит
здоровой, и единственный след её работы — то, что она сама о себе сообщает.

Ровно так и жила мёртвая обрезка потоков чата: `cleanup_old_streams` месяцами возвращала
`{"status": "success", "trimmed": 0}` при 112 потоках, и «0» был единственной уликой.
Поэтому проверяем не «не упало», а ЧТО ИМЕННО задача о себе говорит.

⚠️ Покрытие этого модуля было 28% — самое низкое среди инфраструктуры, и именно здесь
нашлась поломка. Тесты писались от поведения, а не ради процента.
"""

from __future__ import annotations

import asyncio

import pytest

from service.infrastructure.messaging import tasks


class _Mailer:
    """Двойник SMTP: запоминает, что отправляли."""

    sent: list[dict] = []

    def __init__(self, _cfg):
        pass

    async def send(self, *, to, subject, html, text):
        _Mailer.sent.append({"to": to, "subject": subject, "html": html, "text": text})


class _FailingMailer:
    def __init__(self, _cfg):
        pass

    async def send(self, **_kw):
        raise RuntimeError("SMTP отказал")


@pytest.fixture(autouse=True)
def _clean():
    _Mailer.sent = []
    yield
    _Mailer.sent = []


# --- письма ---------------------------------------------------------------------------- #


def test_verification_email_reports_sent(monkeypatch):
    monkeypatch.setattr("service.infrastructure.mail.smtp_mailer.SmtpMailer", _Mailer)

    result = tasks.send_verification_email("a@b.c", "тема", "<b>код</b>", "код")

    assert result == {"status": "sent"}
    assert _Mailer.sent[0]["to"] == "a@b.c"


def test_a_failed_email_names_its_reason(monkeypatch):
    """🔴 «error» без причины бесполезен: Celery видит успех, и разбираться будет НЕ С ЧЕМ."""
    monkeypatch.setattr("service.infrastructure.mail.smtp_mailer.SmtpMailer", _FailingMailer)

    result = tasks.send_verification_email("a@b.c", "тема", "html", "text")

    assert result["status"] == "error"
    assert "SMTP отказал" in result["error"], "причина потеряна — отлаживать будет нечем"


def test_receipt_email_is_rendered_not_empty(monkeypatch):
    """⚠️ Письмо об оплате транзакционное и шлётся ВСЕГДА: пустой шаблон — молчаливая
    потеря подтверждения для человека, который заплатил."""
    monkeypatch.setattr("service.infrastructure.mail.smtp_mailer.SmtpMailer", _Mailer)

    result = tasks.send_payment_receipt_email("a@b.c", credits=500, amount_rub=299.0, plan=None)

    assert result == {"status": "sent"}
    sent = _Mailer.sent[0]
    assert sent["subject"] and sent["html"] and sent["text"]
    assert "500" in sent["html"] or "500" in sent["text"], "число кредитов в письме не названо"


def test_a_failed_receipt_email_names_its_reason(monkeypatch):
    monkeypatch.setattr("service.infrastructure.mail.smtp_mailer.SmtpMailer", _FailingMailer)

    result = tasks.send_payment_receipt_email("a@b.c", credits=1, amount_rub=1.0)

    assert result["status"] == "error" and result["error"]


# --- обрезка потоков ------------------------------------------------------------------- #


def _config(redis_enabled: bool):
    """Двойник конфига: задачи создают `Config()` ВНУТРИ себя, подменяем на источнике."""

    class _Redis:
        enabled = redis_enabled
        host, port, db, password, use_ssl = "localhost", 6379, 0, None, False

    class _Cfg:
        redis = _Redis()

    return lambda: _Cfg()


def test_trim_reports_how_many_streams_it_touched(monkeypatch):
    """🔴 ГЛАВНОЕ. Число — единственная улика: месяцами здесь стоял НОЛЬ при 112 потоках,
    и по «success» это было неотличимо от работающей задачи."""
    seen = {}

    async def _cleanup(_client, *, pattern, maxlen):
        seen.update({"pattern": pattern, "maxlen": maxlen})
        return 7

    monkeypatch.setattr("service.settings.Config", _config(True))
    monkeypatch.setattr(
        "service.infrastructure.cache.redis_manager.RedisManager.get_client",
        lambda self: object(),
    )
    monkeypatch.setattr(
        "service.infrastructure.messaging.stream_helpers.cleanup_old_streams", _cleanup
    )

    result = tasks.cleanup_old_streams()

    assert result == {"status": "success", "trimmed": 7}
    assert seen == {"pattern": "chat:*:stream", "maxlen": 1000}, (
        "задача обрезает не потоки чата или не по тому потолку"
    )


def test_trim_says_skipped_when_redis_is_off(monkeypatch):
    """🔴 «Пропущено» и «сделано» — РАЗНЫЕ вещи. Ответив «success» при выключенном Redis,
    задача заявляла бы работу, которой не было."""
    monkeypatch.setattr("service.settings.Config", _config(False))

    result = tasks.cleanup_old_streams()

    assert result["status"] == "skipped"
    assert result["reason"] == "redis_disabled"


def test_a_broken_trim_reports_error_with_a_reason(monkeypatch):
    """⚠️ Задача глотает исключения по построению — тем важнее, что причина ДОЕЗЖАЕТ."""

    async def _boom(*_a, **_kw):
        raise RuntimeError("redis лёг")

    monkeypatch.setattr("service.settings.Config", _config(True))
    monkeypatch.setattr(
        "service.infrastructure.cache.redis_manager.RedisManager.get_client",
        lambda self: object(),
    )
    monkeypatch.setattr(
        "service.infrastructure.messaging.stream_helpers.cleanup_old_streams", _boom
    )

    result = tasks.cleanup_old_streams()

    assert result["status"] == "error"
    assert "redis лёг" in result["error"]


# --- сверка платежей и провайдеров ----------------------------------------------------- #


def test_reconcile_passes_the_service_result_through(monkeypatch):
    """⚠️ Задача сверяет ПЛАТЕЖИ: проглоченный результат означал бы, что до-начисление
    прошло, а узнать об этом нельзя."""

    class _Service:
        async def reconcile_pending_payments(self):
            return {"checked": 3, "credited": 1}

    monkeypatch.setattr(
        "service.services.billing.application.billing_service.BillingService",
        lambda *_a, **_kw: _Service(),
    )
    monkeypatch.setattr(
        "service.services.billing.infrastructure.payments.factory.build_payment_provider",
        lambda _cfg: object(),
    )
    monkeypatch.setattr(
        "service.infrastructure.database.postgresql.PgConnector",
        lambda _cfg, **_kwargs: object(),
    )

    result = tasks.reconcile_pending_payments()

    assert result == {"status": "success", "checked": 3, "credited": 1}


def test_a_broken_reconcile_reports_error(monkeypatch):
    """🔴 Молчаливый отказ сверки = потерянная оплата, о которой никто не узнает."""

    class _Service:
        async def reconcile_pending_payments(self):
            raise RuntimeError("провайдер недоступен")

    monkeypatch.setattr(
        "service.services.billing.application.billing_service.BillingService",
        lambda *_a, **_kw: _Service(),
    )
    monkeypatch.setattr(
        "service.services.billing.infrastructure.payments.factory.build_payment_provider",
        lambda _cfg: object(),
    )
    monkeypatch.setattr(
        "service.infrastructure.database.postgresql.PgConnector",
        lambda _cfg, **_kwargs: object(),
    )

    result = tasks.reconcile_pending_payments()

    assert result["status"] == "error"
    assert "провайдер недоступен" in result["error"]


def test_provider_pricing_refresh_reports_catalog_counts(monkeypatch):
    seen = {}

    class _Service:
        async def refresh(self):
            return {"providers": 2, "replaced": 789, "deleted": 12}

    class _Connector:
        def __init__(self, _cfg):
            seen["constructed_in_running_loop"] = not asyncio.get_running_loop().is_closed()

    monkeypatch.setattr(
        "service.services.billing.application.provider_pricing_sync.ProviderPricingSyncService",
        lambda *_a, **_kw: _Service(),
    )
    monkeypatch.setattr("service.infrastructure.database.postgresql.PgConnector", _Connector)

    result = tasks.refresh_provider_pricing()

    assert result == {"status": "success", "providers": 2, "replaced": 789, "deleted": 12}
    assert seen["constructed_in_running_loop"] is True


def test_reservation_cleanup_constructs_connector_inside_task_loop(monkeypatch):
    seen = {}

    class _Config:
        pg = object()

    class _Connector:
        def __init__(self, _cfg):
            seen["constructed_in_running_loop"] = not asyncio.get_running_loop().is_closed()

    async def _cleanup(_repo):
        return {"expired": 2, "active": 3}

    monkeypatch.setattr("service.settings.Config", lambda: _Config())
    monkeypatch.setattr("service.infrastructure.database.postgresql.PgConnector", _Connector)
    monkeypatch.setattr(
        "service.services.billing.persistence.billing_repository.BillingRepository",
        lambda _connector: object(),
    )
    monkeypatch.setattr(
        "service.services.billing.application.cost_guard.cleanup_expired_reservations", _cleanup
    )

    result = tasks.cleanup_expired_reservations()

    assert result == {"status": "success", "expired": 2, "active": 3}
    assert seen["constructed_in_running_loop"] is True


def test_provider_pricing_refresh_reports_catalog_failure(monkeypatch):
    class _Service:
        async def refresh(self):
            raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(
        "service.services.billing.application.provider_pricing_sync.ProviderPricingSyncService",
        lambda *_a, **_kw: _Service(),
    )
    monkeypatch.setattr(
        "service.infrastructure.database.postgresql.PgConnector", lambda _cfg: object()
    )

    result = tasks.refresh_provider_pricing()

    assert result["status"] == "error"
    assert "catalog unavailable" in result["error"]


def test_every_task_returns_a_status(monkeypatch):
    """⚠️ КОНТРАКТ ОДИН НА ВСЕ ЗАДАЧИ. Задача без `status` неотличима от упавшей: Celery
    в обоих случаях запишет успех, а прочитать результат будет нечем.

    Разбираем ДЕРЕВО: подпись `-> dict` ничего не гарантирует, а строка `"status"` могла бы
    оказаться в комментарии.
    """
    import ast
    import inspect

    source = inspect.getsource(tasks)
    tree = ast.parse(source)
    periodic = {
        "cleanup_old_streams",
        "recheck_blocked_providers",
        "reconcile_pending_payments",
        "cleanup_expired_reservations",
        "refresh_provider_pricing",
        "send_verification_email",
        "send_payment_receipt_email",
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in periodic:
            continue
        returns = [n for n in ast.walk(node) if isinstance(n, ast.Return) and n.value is not None]
        assert returns, f"{node.name}: ничего не возвращает — результат задачи нечитаем"
        keys = {
            const.value
            for r in returns
            for const in ast.walk(r)
            if isinstance(const, ast.Constant) and isinstance(const.value, str)
        }
        assert "status" in keys, f"{node.name}: в ответе нет `status`"
