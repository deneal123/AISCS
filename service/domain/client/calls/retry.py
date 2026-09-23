"""Классификация ошибок LLM-вызовов и ретраи с экспоненциальным backoff.

Используется фасадом клиента (Фаза 1: ретраи/фейловер) и слоем категоризации
ошибок (Фаза 3). Не зависит от конкретного провайдера.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

ErrorCategory = Literal["transient", "rate_limit", "timeout", "auth", "config", "fatal"]

# Категории, которые имеет смысл повторять на ТОМ ЖЕ провайдере.
_RETRYABLE: frozenset[str] = frozenset({"transient", "rate_limit", "timeout"})

# openai исключения импортируем мягко — имена стабильны в openai>=1.0, но в
# минимальных окружениях модуль может отсутствовать.
try:  # pragma: no cover - тривиальный импорт
    from openai import (
        APIConnectionError,
        APIError,
        APIStatusError,
        APITimeoutError,
        AuthenticationError,
        BadRequestError,
        InternalServerError,
        NotFoundError,
        PermissionDeniedError,
        RateLimitError,
    )

    _OPENAI_AVAILABLE = True
except Exception:  # pragma: no cover
    APIError = APIStatusError = APITimeoutError = APIConnectionError = ()  # type: ignore
    AuthenticationError = PermissionDeniedError = RateLimitError = ()  # type: ignore
    BadRequestError = NotFoundError = InternalServerError = ()  # type: ignore
    _OPENAI_AVAILABLE = False


def _status_code(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    resp = getattr(exc, "response", None)
    code = getattr(resp, "status_code", None)
    return code if isinstance(code, int) else None


def classify_error(exc: Exception) -> ErrorCategory:
    """Свести исключение к категории для решения о ретрае/фейловере/UX-сообщении."""
    # Таймауты (asyncio / httpx / openai).
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if _OPENAI_AVAILABLE and isinstance(exc, APITimeoutError):
        return "timeout"

    # Сетевые/соединительные — транзиентные.
    if isinstance(exc, (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError)):
        return "transient"
    if _OPENAI_AVAILABLE and isinstance(exc, APIConnectionError):
        return "transient"

    # Лимиты.
    if _OPENAI_AVAILABLE and isinstance(exc, RateLimitError):
        return "rate_limit"

    # Авторизация/доступ.
    if _OPENAI_AVAILABLE and isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return "auth"

    # Явно не повторяемое (плохой запрос/модель не найдена у провайдера).
    if _OPENAI_AVAILABLE and isinstance(exc, (BadRequestError, NotFoundError)):
        return "config"

    # 5xx — транзиентные; по статус-коду, если доступен.
    if _OPENAI_AVAILABLE and isinstance(exc, InternalServerError):
        return "transient"

    code = _status_code(exc)
    if code is not None:
        if code == 429:
            return "rate_limit"
        if code in (401, 403):
            return "auth"
        if code in (400, 404, 422):
            return "config"
        if 500 <= code < 600:
            return "transient"

    # Прочие httpx-ошибки трактуем как транзиентные сетевые.
    if isinstance(exc, httpx.HTTPError):
        return "transient"

    return "fatal"


def is_retryable(exc: Exception) -> bool:
    return classify_error(exc) in _RETRYABLE


def _backoff_delay(attempt: int, base_delay: float, max_delay: float) -> float:
    """Full-jitter экспоненциальный backoff: random(0, min(max, base*2**attempt))."""
    ceiling = min(max_delay, base_delay * (2**attempt))
    if ceiling <= 0:
        return 0.0
    return random.uniform(0.0, ceiling)


async def with_retry(
    fn: Callable[[], Awaitable[Any]],
    *,
    attempts: int = 2,
    base_delay: float = 0.4,
    max_delay: float = 4.0,
    label: str = "llm-call",
) -> Any:
    """Выполнить async-вызов с ретраями только по повторяемым категориям.

    ``attempts`` — общее число попыток (1 = без ретраев). Неповторяемые ошибки
    (auth/config/fatal) пробрасываются немедленно — выше по стеку их обрабатывает
    фейловер (следующий провайдер).
    """
    total = max(1, int(attempts))
    last_exc: Exception | None = None
    for attempt in range(total):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 — классифицируем ниже
            last_exc = exc
            category = classify_error(exc)
            if category not in _RETRYABLE or attempt >= total - 1:
                raise
            delay = _backoff_delay(attempt, base_delay, max_delay)
            logger.warning(
                "%s failed (%s), retry %d/%d in %.2fs",
                label,
                category,
                attempt + 1,
                total - 1,
                delay,
            )
            if delay > 0:
                await asyncio.sleep(delay)
    # недостижимо: последний проход либо вернул, либо пробросил
    assert last_exc is not None
    raise last_exc


def retry_params() -> dict:
    """Параметры ретраев для фасадных вызовов: попыток и задержки.

    ⚠️ Живёт ЗДЕСЬ, а не у вызывающих. Раньше `_retry_params` лежал в фасаде и был
    нужен и не-стримовому пути, и стримовому; после разделения на модули он бы либо
    продублировался, либо связал их друг с другом ради трёх строк. Число попыток
    приезжает из админ-overlay, поэтому читается на КАЖДЫЙ вызов, а не кэшируется.
    """
    from service.settings import config
    from service.shared.agent_settings import runtime_settings

    return {
        "attempts": runtime_settings.get_agents(
            "llm_retry_attempts", config.agents.llm_retry_attempts
        ),
        "base_delay": config.agents.llm_retry_base_delay_sec,
        "max_delay": config.agents.llm_retry_max_delay_sec,
    }
