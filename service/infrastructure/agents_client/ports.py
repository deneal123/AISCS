"""Порты, по которым backend и сайдкар говорят друг с другом.

Это КОНТРАКТЫ, а не реализация: чистые Protocol'ы без зависимостей. Жили они в
``agents/application/ports`` — то есть внутри домена, который уезжает в сайдкар. Из-за
этого backend был вынужден импортировать домен ради одного описания интерфейса: воркер
типизирует им движок (``AgentExecutionPort``), а messaging — публикацию событий
(``StreamPort``).

Контракту место в общем ядре: им пользуются ОБЕ стороны, и ни одна не должна ради него
тащить чужой код.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class StreamPort(Protocol):
    """Публикация события в поток (Redis-стрим чата). Реализует backend."""

    async def publish(self, stream: str, payload: dict[str, Any]) -> None: ...


@runtime_checkable
class AgentExecutionPort(Protocol):
    """Прогон агента. Реализуют оба: движок in-process и ``HttpAgentEngine``."""

    async def execute(self, **kwargs: Any) -> dict[str, Any]: ...


# --------------------------------------------------------------------------- utils --
ANON_USER_UUID = UUID("00000000-0000-0000-0000-000000000000")


def resolve_user_uuid(
    user_id: str | int | UUID | None, *, anonymous_fallback: bool = True
) -> UUID | None:
    """Нормализовать идентификатор пользователя к UUID.

    Живёт в общем ядре, потому что нужен ОБЕИМ сторонам: backend адресует им файлы и
    временные загрузки, домен (duckdb-инструмент) — выборку файлов пользователя. Чистая
    функция без зависимостей, ради неё тащить чужой пакет незачем.

    ``anonymous_fallback`` различает два случая: «аноним допустим» (загрузка во временную
    сессию) и «нужен реальный пользователь» (выборка его файлов). Спутать их — отдать
    анониму чужие данные или наоборот потерять файлы владельца.
    """
    if isinstance(user_id, UUID):
        return user_id
    if user_id is None:
        return ANON_USER_UUID if anonymous_fallback else None

    normalized = str(user_id).strip()
    # "none"/"null" ловим ЯВНО: сюда регулярно приезжает застрингифаенный None, и хотя
    # UUID() его тоже отвергнет, намерение должно читаться, а не выводиться из исключения.
    if not normalized or normalized.lower() in {"none", "null"}:
        return ANON_USER_UUID if anonymous_fallback else None
    try:
        return UUID(normalized)
    except (ValueError, AttributeError, TypeError):
        return ANON_USER_UUID if anonymous_fallback else None
