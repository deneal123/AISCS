"""Категоризация ошибок агентского прогона для UX и метрик (Фаза 3).

Опирается на client.retry.classify_error и переводит технические категории в
пользовательские (network/timeout/rate_limit/auth/config/provider/unknown) с
безопасным сообщением.
"""

from __future__ import annotations

from dataclasses import dataclass

from service.domain.client.calls.retry import classify_error

# Техническая категория retry → пользовательская категория.
_CATEGORY_MAP = {
    "transient": "network",
    "timeout": "timeout",
    "rate_limit": "rate_limit",
    "auth": "auth",
    "config": "config",
    "fatal": "unknown",
}

_USER_MESSAGES = {
    "network": "Временная ошибка соединения с моделью. Попробуйте ещё раз.",
    "timeout": "Превышено время ожидания ответа модели. Попробуйте ещё раз.",
    "rate_limit": "Слишком много запросов к модели. Повторите через несколько секунд.",
    "auth": "Ошибка авторизации у провайдера модели. Обратитесь к администратору.",
    "config": "Некорректный запрос к модели.",
    "provider": "Провайдер модели временно недоступен.",
    "unknown": "Не удалось обработать запрос. Попробуйте ещё раз.",
}


@dataclass(frozen=True)
class CategorizedError:
    category: str
    user_message: str
    error_type: str


def categorize(exc: Exception) -> CategorizedError:
    # `asyncio.TimeoutError` — с Python 3.11 ПСЕВДОНИМ встроенного `TimeoutError` (проверено
    # на 3.13, которую требует проект: `is` даёт True). Кортеж из двух имён одного объекта
    # и отложенный импорт `asyncio` ради него ничего не проверяли.
    if isinstance(exc, TimeoutError):
        category = "timeout"
    else:
        category = _CATEGORY_MAP.get(classify_error(exc), "unknown")
    return CategorizedError(
        category=category,
        user_message=_USER_MESSAGES.get(category, _USER_MESSAGES["unknown"]),
        error_type=type(exc).__name__,
    )
