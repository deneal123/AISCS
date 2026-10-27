from unittest.mock import AsyncMock

import pytest

from service.infrastructure.mail.smtp_mailer import MailSendError, SmtpMailer
from service.settings import EmailConfig


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tls", "start_tls", "login", "password", "expected_start_tls"),
    [
        (False, False, "", "", False),
        (False, True, "test-login", "test-password", True),
        (True, True, "test-login", "test-password", None),
    ],
)
async def test_smtp_transport_modes(
    monkeypatch, tls, start_tls, login, password, expected_start_tls
):
    send = AsyncMock()
    monkeypatch.setattr("aiosmtplib.send", send)
    config = EmailConfig(
        host="mailpit",
        port=1025,
        use_tls=tls,
        start_tls=start_tls,
        login=login,
        password=password,
        from_address="no-reply@gpthub.test",
    )
    await SmtpMailer(config).send(
        to="recipient@example.com", subject="test", html="<b>test</b>", text="test"
    )
    arguments = send.call_args.kwargs
    assert arguments["start_tls"] is expected_start_tls
    assert arguments["use_tls"] is tls
    assert arguments["username"] == (login or None)
    assert arguments["password"] == (password or None)
    assert send.call_args.args[0].is_multipart()
    send.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host,login,password", [("", "", ""), ("smtp", "login", ""), ("smtp", "", "password")]
)
async def test_invalid_smtp_configuration_does_not_connect(monkeypatch, host, login, password):
    send = AsyncMock()
    monkeypatch.setattr("aiosmtplib.send", send)
    with pytest.raises(MailSendError, match="^smtp_config$"):
        await SmtpMailer(EmailConfig(host=host, login=login, password=password)).send(
            to="recipient@example.com", subject="test", html="test", text="test"
        )
    send.assert_not_called()


@pytest.mark.asyncio
async def test_smtp_failure_is_bounded(monkeypatch, caplog):
    marker = "PRIVATE_SMTP_RESPONSE_BODY"
    monkeypatch.setattr("aiosmtplib.send", AsyncMock(side_effect=RuntimeError(marker)))
    with pytest.raises(MailSendError, match="^smtp_unavailable$") as failure:
        await SmtpMailer(EmailConfig(host="mailpit", login="", password="")).send(
            to="private-recipient@example.com", subject="test", html="test", text="test"
        )
    assert marker not in caplog.text
    assert "private-recipient" not in caplog.text
    assert failure.value.__suppress_context__


def test_production_tls_defaults_are_preserved(monkeypatch):
    for name in ("MAIL__USE_TLS", "MAIL__START_TLS"):
        monkeypatch.delenv(name, raising=False)
    config = EmailConfig()
    assert config.use_tls is True
    assert config.start_tls is True


@pytest.mark.asyncio
async def test_dispatcher_fallback_does_not_log_code_or_broker_body(monkeypatch, caplog):
    from service.infrastructure.mail.dispatcher import VerificationCodeDispatcher

    def unavailable(*args):
        raise RuntimeError("PRIVATE_BROKER_RESPONSE")

    monkeypatch.setattr(
        "service.infrastructure.messaging.tasks.send_verification_email.delay", unavailable
    )
    mailer = AsyncMock()
    dispatcher = VerificationCodeDispatcher(mailer, enabled=True, dev_mode=True, ttl_seconds=600)
    await dispatcher.send(email="private-recipient@example.com", code="987654", purpose="register")
    mailer.send.assert_awaited_once()
    assert "987654" not in caplog.text
    assert "private-recipient" not in caplog.text
    assert "PRIVATE_BROKER_RESPONSE" not in caplog.text
