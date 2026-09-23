"""Область действия личности на один прогон.

Тот же приём, что у снимка админ-настроек (`shared/agent_settings.py`) и провайдерной
политики: значение живёт в ContextVar и не протекает в чужой параллельный прогон.

🔴 НО С ОДНИМ ОБЯЗАТЕЛЬНЫМ ОТЛИЧИЕМ: ЗДЕСЬ НЕТ ПРОЦЕССНОГО ФОЛБЭКА. У настроек он есть
(`_LAST_SEEN`) — и там это оправдано: снимок админки одинаков для всех, а путь `/v1`
своего не приносит, поэтому лучше применить последний виденный, чем молча уехать на
дефолты. С личностью ровно наоборот: она принадлежит КОНКРЕТНОМУ пользователю и
конкретному сообщению. «Последняя виденная» здесь означала бы, что личность прошлого
запроса подмешается в запрос, где её не просили, — то есть чужая специализация в чужом
ответе. Нет линзы в прогоне → нейтральное поведение, и никогда «как в прошлый раз».

Отсюда же место установки: область ставится в `execute` (обычная корутина), а НЕ внутри
асинхронного генератора процессора. `ContextVar.reset` в генераторе может выполниться в
другом контексте — эта причина уже задокументирована рядом, у `step_timing.collect()`
в `application/agent_execution_service.py`.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — только для типов
    from service.domain.persona.lens import PersonaLens

_PERSONA: ContextVar[PersonaLens | None] = ContextVar("gpthub_persona_lens", default=None)


@contextlib.contextmanager
def use_persona(lens: PersonaLens | None) -> Iterator[None]:
    """Применить личность на время прогона. `None` — прогон без личности."""
    token = _PERSONA.set(lens)
    try:
        yield
    finally:
        _PERSONA.reset(token)


def current() -> PersonaLens:
    """Линза текущего прогона. Всегда объект — вызывающему не нужно проверять `None`.

    Без активной личности возвращается ПУСТАЯ линза: все её слоты дают `""`, то есть
    поведение остаётся ровно прежним. Это делает впрыск безопасным в любом месте кода —
    подмешивание пустой строки не меняет промпт.
    """
    from service.domain.persona.lens import EMPTY_LENS

    return _PERSONA.get() or EMPTY_LENS
