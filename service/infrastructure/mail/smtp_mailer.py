from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import Protocol, runtime_checkable

from service.settings import EmailConfig

logger = logging.getLogger(__name__)


class MailSendError(RuntimeError):
    """SMTP-отправка не удалась (сеть/аутентификация/провайдер)."""


@runtime_checkable
class MailPort(Protocol):
    async def send(self, *, to: str, subject: str, html: str, text: str) -> None: ...


class SmtpMailer:
    """Асинхронный SMTP-мейлер на aiosmtplib.

    Порт 1127 → implicit TLS (`use_tls=True`); 1126 → STARTTLS (`use_tls=False`).
    """

    def __init__(self, config: EmailConfig) -> None:
        self._config = config

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        cfg = self._config
        if not cfg.host or not cfg.login:
            raise MailSendError("SMTP is not configured (MAIL__HOST / MAIL__LOGIN missing)")

        # Импорт внутри метода — чтобы отсутствие пакета не ломало импорт модуля
        # в окружениях, где почта не используется.
        import aiosmtplib

        message = EmailMessage()
        message["From"] = f"{cfg.from_name or 'GPTHub'} <{cfg.from_address}>"
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        message.add_alternative(html, subtype="html")

        try:
            await aiosmtplib.send(
                message,
                hostname=cfg.host,
                port=cfg.port,
                username=cfg.login,
                password=cfg.password,
                use_tls=cfg.use_tls,  # implicit TLS (1127)
                start_tls=None if cfg.use_tls else True,  # STARTTLS (1126)
                timeout=cfg.timeout_sec,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("SMTP send failed to %s", to)
            raise MailSendError(str(exc)) from exc
