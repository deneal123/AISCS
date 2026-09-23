"""Первые события прогона доезжают до браузера, а не теряются в зазоре подписки.

🔴 НАЙДЕНО ЖИВЫМ ПРОГОНОМ. В Redis-потоке события `auto_decision` и `mode_offer` ЕСТЬ
(проверено `XRANGE`), а в трейсе первых шагов нет вовсе. Причина: `XREAD` со «$»
фиксирует курсор В МОМЕНТ ЧТЕНИЯ, а задача-потребитель стартовала асинхронно — её первый
блокирующий вызов случался уже после того, как сокет начал принимать сообщения и воркер
успевал опубликовать начало прогона.

До переезда карточки режима в трейс это стоило одной строки в панели. После — стоит
САМОГО ПРЕДЛОЖЕНИЯ: оно живёт шагом трейса, и терялось целиком.

⚠️ Фолбэк — «$», а не «0-0»: не смогли узнать хвост — деградируем до прежнего поведения,
а не до чтения потока с начала (на треде с историей это переиграло бы клиенту тысячи
старых чанков).
"""

from __future__ import annotations

import ast
import inspect

import pytest

from service.infrastructure.messaging import stream_helpers
from service.services.chat.presentation.ws.chat_ws.stream_consumer import ChatStreamConsumer


class _Redis:
    """Двойник асинхронного клиента.

    ⚠️ `execute_command` ОБЯЗАТЕЛЕН, и это не формальность: по нему код и узнаёт, что клиент
    асинхронный. У настоящего `redis.asyncio` он объявлен `async def`, а команды — обычные
    методы, возвращающие корутину; двойник без него выглядит как СИНХРОННЫЙ, и вызов уходит
    в `to_thread`. Раньше проверка шла по самой команде — и этот двойник проходил, хотя на
    настоящем клиенте та же проверка отвечает ЛОЖЬ. То есть тест был зелен от формы
    двойника, а не от поведения кода.
    """

    def __init__(self, last: object = None, boom: bool = False):
        self._last = last
        self._boom = boom

    async def execute_command(self, *args, **kwargs):
        return None

    async def xinfo_stream(self, stream):
        if self._boom:
            raise RuntimeError("no such key")
        return {"length": 3, "last-entry": self._last}

    async def xinfo_groups(self, stream):
        return []


def _consumer(redis) -> ChatStreamConsumer:
    return ChatStreamConsumer(redis, settings=object(), metrics=_Metrics())


class _Metrics:
    def inc(self, *_a, **_kw):
        return None


@pytest.mark.asyncio
async def test_cursor_is_a_concrete_id_not_a_late_dollar():
    """⚠️ ГЛАВНОЕ. Курсор — КОНКРЕТНЫЙ идентификатор хвоста, разрешённый заранее."""
    redis = _Redis(last=("1785224000-5", {"data": "{}"}))

    cursor = await _consumer(redis).resolve_cursor("chat:t:stream", True)

    assert cursor == "1785224000-5"


@pytest.mark.asyncio
async def test_empty_stream_starts_from_the_beginning_safely():
    """Пустой поток: хвоста нет, и «0-0» здесь безопасно — переигрывать нечего."""
    cursor = await _consumer(_Redis(last=None)).resolve_cursor("chat:t:stream", True)

    assert cursor == "$"


@pytest.mark.asyncio
async def test_unreadable_tail_degrades_to_dollar_not_to_history():
    """⚠️ Фолбэк в СТОРОНУ прежнего поведения: «0-0» переиграл бы всю историю треда."""
    cursor = await _consumer(_Redis(boom=True)).resolve_cursor("chat:t:stream", True)

    assert cursor == "$"


@pytest.mark.asyncio
async def test_replay_mode_still_reads_from_the_beginning():
    """`start_from_latest=False` — это осознанное «с начала», его не ломаем."""
    cursor = await _consumer(_Redis()).resolve_cursor("chat:t:stream", False)

    assert cursor == "0"


@pytest.mark.asyncio
async def test_tail_id_helper_survives_a_bytes_answer():
    """Клиент Redis может отдать идентификатор байтами — курсор обязан остаться строкой."""
    redis = _Redis(last=(b"1785224000-7", {}))

    assert await stream_helpers.last_entry_id(redis, "chat:t:stream") == "1785224000-7"


def test_cursor_is_resolved_before_messages_are_accepted():
    """🔴 ТОЧКА ВЫЗОВА И ПОРЯДОК. Разреши курсор позже приёма сообщений — гонка вернётся.

    Проверяем структурно: `resolve_cursor` вызывается ДО `handle_incoming_messages`.
    Тесты выше проверяют саму функцию и остались бы зелёными при любом порядке — а
    именно порядок и был дефектом.
    """
    import textwrap

    from service.services.chat.presentation.ws.chat_ws import connection as conn

    source = textwrap.dedent(inspect.getsource(conn.ChatWsConnectionService.run))
    tree = ast.parse(source)
    order: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("resolve_cursor", "handle_incoming_messages"):
                order.append(f"{node.func.attr}:{node.lineno}")

    names = [item.split(":")[0] for item in sorted(order, key=lambda s: int(s.split(":")[1]))]
    assert names == ["resolve_cursor", "handle_incoming_messages"], (
        f"курсор разрешается не до приёма сообщений — первые события снова потеряются: {names}"
    )
