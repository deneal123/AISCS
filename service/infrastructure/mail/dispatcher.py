from __future__ import annotations

import asyncio
import logging

from service.infrastructure.mail.smtp_mailer import MailPort
from service.infrastructure.mail.templates import build_verification_email

logger = logging.getLogger(__name__)


class VerificationCodeDispatcher:
    """Async-отправитель кода подтверждения (реализация `VerificationCodeSenderPort`).

    Строит письмо и ставит Celery-таск (воркер = SMTP-клиент, HTTP-запрос не ждёт
    отправки). При недоступности брокера — отправляет инлайн. Ошибки отправки
    НЕ пробрасываются: код уже сохранён в Redis, пользователь может нажать «повторить».
    В `dev_mode` код логируется (для E2E/отладки без реальной почты); при
    `enabled=False` письмо не шлётся (код доступен только в логах — удобно в dev).
    """

    def __init__(
        self,
        mailer: MailPort,
        *,
        enabled: bool,
        dev_mode: bool,
        ttl_seconds: int,
    ) -> None:
        self._mailer = mailer
        self._enabled = enabled
        self._dev_mode = dev_mode
        self._ttl_seconds = ttl_seconds

    async def send(self, *, email: str, code: str, purpose: str) -> None:
        if self._dev_mode:
            logger.info("DEV verification code for %s: %s", email, code)
        if not self._enabled:
            logger.info("MAIL__ENABLED=false → verification email not sent (code logged only)")
            return

        ttl_minutes = max(1, round(self._ttl_seconds / 60))
        subject, html, text = build_verification_email(code, purpose, ttl_minutes)

        # 1) Асинхронно через Celery (maintenance-очередь). `.delay()` — блокирующая
        #    публикация в брокер, поэтому уводим в тред, чтобы не держать event loop.
        try:
            from service.infrastructure.messaging import tasks

            await asyncio.to_thread(tasks.send_verification_email.delay, email, subject, html, text)
            return
        except Exception:
            logger.warning(
                "Celery enqueue of verification email failed; sending inline", exc_info=True
            )

        # 2) Фолбэк — прямая отправка (напр. брокер недоступен). Не роняем флоу.
        try:
            await self._mailer.send(to=email, subject=subject, html=html, text=text)
        except Exception:
            logger.exception("Inline verification email send failed for %s", email)
