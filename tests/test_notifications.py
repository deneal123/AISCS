"""Жизненные уведомления: согласие, отписка, идемпотентность, частотный лимит.

Это письма ЖИВЫМ ЛЮДЯМ, поэтому тесты здесь не про «работает ли код», а про то, что мы
никому не напишем лишнего:

* реклама уходит только при отдельном согласии (ФЗ «О рекламе», ст. 18 — согласие на
  обработку ПДн рекламу НЕ покрывает);
* отписка гасит всё, включая сервисные письма;
* beat крутится по расписанию — без dedup одно письмо ушло бы каждый прогон.
"""

from types import SimpleNamespace

import pytest

from service.services.notifications.notification_service import (
    MARKETING_KINDS,
    SERVICE_KINDS,
    NotificationService,
    unsubscribe_token,
    verify_unsubscribe_token,
)


# --------------------------------------------------------------------------- #
# Отписка: подпись                                                             #
# --------------------------------------------------------------------------- #
def test_unsubscribe_token_is_signed():
    """Без подписи ссылка `?u=<uuid>` позволяла бы отписать ЛЮБОГО, подставив чужой id."""
    token = unsubscribe_token("user-1", "secret")
    assert verify_unsubscribe_token("user-1", token, "secret") is True
    # Чужой id той же подписью не проходит.
    assert verify_unsubscribe_token("user-2", token, "secret") is False
    # Другой секрет — тоже.
    assert verify_unsubscribe_token("user-1", token, "other") is False


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "deadbeef",
        None,
        # Не-ASCII: hmac.compare_digest КИДАЕТ TypeError на таком str. Раньше здесь была
        # только латиница — и публичный эндпоинт отписки падал в 500 вместо 403.
        "подделка",
        "🙂",
    ],
)
def test_unsubscribe_rejects_garbage_tokens(bad):
    assert verify_unsubscribe_token("user-1", bad, "secret") is False


# --------------------------------------------------------------------------- #
# Категории писем                                                              #
# --------------------------------------------------------------------------- #
def test_reactivation_is_the_only_marketing_kind():
    """Сервисные письма — состояние аккаунта. Реактивация — реклама, и она одна."""
    assert MARKETING_KINDS == {"reactivation"}
    assert SERVICE_KINDS == {"subscription_expiring", "low_credits", "payment_failed"}
    assert not (SERVICE_KINDS & MARKETING_KINDS)


# --------------------------------------------------------------------------- #
# Гейты отправки                                                               #
# --------------------------------------------------------------------------- #
def _config(**over):
    defaults = {
        "enabled": True,
        "app_url": "https://gpthub.ru",
        "subscription_notice_days": 3,
        "low_credits_threshold": 0.1,
        "idle_days": 30,
        "max_per_window": 1,
        "frequency_window_days": 7,
    }
    notif = SimpleNamespace(**{**defaults, **over})
    return SimpleNamespace(notifications=notif, auth=SimpleNamespace(secret="s" * 16), email=None)


class _Session:
    """Псевдо-сессия: отвечает на два запроса гейта — «уже слали?» и «сколько за окно»."""

    def __init__(self, *, already: bool, recent: int):
        self.already = already
        self.recent = recent
        self.inserted: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "INSERT INTO profile.notification_log" in sql:
            self.inserted.append(params or {})
            return SimpleNamespace(first=lambda: None)
        if "SELECT 1 FROM profile.notification_log" in sql:
            return SimpleNamespace(first=lambda: (1,) if self.already else None)
        if "COUNT(*)" in sql:
            return SimpleNamespace(scalar=lambda: self.recent)
        return SimpleNamespace(first=lambda: None, scalar=lambda: 0)

    async def commit(self):
        return None


class _Pg:
    def __init__(self, session):
        self._session = session

    def get_session_context(self):
        return self._session


@pytest.mark.asyncio
async def test_same_event_is_never_sent_twice():
    """Beat крутится ежедневно. Без dedup «подписка истекает» ушла бы каждый прогон."""
    session = _Session(already=True, recent=0)
    service = NotificationService(_Pg(session), None, _config())

    assert await service._may_send("u1", "subscription_expiring", "2026-08-01") is False


@pytest.mark.asyncio
async def test_frequency_cap_blocks_a_burst():
    """Три сработавших триггера не должны дать три письма за неделю."""
    session = _Session(already=False, recent=1)
    service = NotificationService(_Pg(session), None, _config(max_per_window=1))

    assert await service._may_send("u1", "low_credits", "2026-08") is False


@pytest.mark.asyncio
async def test_first_notification_passes():
    session = _Session(already=False, recent=0)
    service = NotificationService(_Pg(session), None, _config())

    assert await service._may_send("u1", "payment_failed", "pay-1") is True


# --------------------------------------------------------------------------- #
# Отправка: журнал пишется ТОЛЬКО после успеха                                 #
# --------------------------------------------------------------------------- #
class _Mailer:
    def __init__(self, boom=False):
        self.boom = boom
        self.sent: list[dict] = []

    async def send(self, *, to, subject, html, text):
        if self.boom:
            raise RuntimeError("SMTP лёг")
        self.sent.append({"to": to, "subject": subject, "html": html, "text": text})


@pytest.mark.asyncio
async def test_every_email_carries_an_unsubscribe_link():
    """Без неё единственный способ прекратить рассылку — пометить нас спамом."""
    session = _Session(already=False, recent=0)
    mailer = _Mailer()
    service = NotificationService(_Pg(session), mailer, _config())

    ok = await service._send(
        "subscription_expiring",
        {
            "user_id": "u1",
            "email": "a@b.c",
            "plan": "pro",
            "days_left": 3,
            "dedup_key": "2026-08-01",
        },
    )

    assert ok
    body = mailer.sent[0]
    assert "/api/notifications/unsubscribe?u=u1&t=" in body["html"]
    assert "/api/notifications/unsubscribe?u=u1&t=" in body["text"]


@pytest.mark.asyncio
async def test_failed_send_is_not_logged():
    """Записать в журнал до отправки — значит навсегда заблокировать повтор при сбое
    SMTP: dedup_key занят, и человек не получит письмо вообще."""
    session = _Session(already=False, recent=0)
    service = NotificationService(_Pg(session), _Mailer(boom=True), _config())

    ok = await service._send(
        "payment_failed",
        {"user_id": "u1", "email": "a@b.c", "amount_rub": 990.0, "dedup_key": "pay-1"},
    )

    assert ok is False
    assert session.inserted == []  # журнал пуст — повтор возможен


@pytest.mark.asyncio
async def test_disabled_service_sends_nothing():
    service = NotificationService(_Pg(_Session(already=False, recent=0)), _Mailer(), _config())
    service.config.notifications.enabled = False
    assert await service.run() == {}


# --------------------------------------------------------------------------- #
# Согласие: SQL реактивации обязан требовать marketing_consent_at              #
# --------------------------------------------------------------------------- #
def test_reactivation_query_requires_marketing_consent():
    """Согласие на обработку ПДн рекламу НЕ покрывает. Проверяем сам текст запроса:
    забыть это условие — значит разослать рекламу тем, кто её не просил."""
    import inspect

    source = inspect.getsource(NotificationService._idle_users)
    assert "marketing_consent_at IS NOT NULL" in source


def test_every_trigger_respects_unsubscribe():
    """`unsubscribed_at IS NULL` должно быть в КАЖДОМ запросе: забыть его в одном месте
    значит написать человеку, который явно попросил не писать."""
    import inspect

    for method in (
        NotificationService._expiring_subscriptions,
        NotificationService._low_credits,
        NotificationService._failed_payments,
        NotificationService._idle_users,
    ):
        source = inspect.getsource(method)
        assert "unsubscribed_at IS NULL" in source, f"{method.__name__} не проверяет отписку"
