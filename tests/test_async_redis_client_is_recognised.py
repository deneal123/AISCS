"""Асинхронный клиент Redis узнаётся по `execute_command`, а не по команде.

🔴 ЦЕНА ОШИБКИ — МОЛЧАНИЕ, А НЕ ИСКЛЮЧЕНИЕ. `inspect.iscoroutinefunction(Redis.xtrim)` на
`redis.asyncio` отвечает ЛОЖЬ: команды там обычные методы, возвращающие корутину. Клиент
уходил в `to_thread`, тот возвращал НЕ ДОЖДАННУЮ корутину, и команда не исполнялась вовсе.

Найдено живым прогоном ДВАЖДЫ. Первый раз — привязка песочницы не писалась и не читалась,
и панель плодила контейнеры. Второй — периодическая обрезка потоков чата не обрезала
НИЧЕГО: 112 потоков в dev-базе, самый длинный 992 записи при потолке 1000, и остановить
его рост было нечем. Замер после починки: та же задача вернула 112 вместо 0.

⚠️ Клиент-двойник здесь ПОВТОРЯЕТ ФОРМУ настоящего: методы — обычные функции, возвращающие
корутину. Двойник с `async def` прошёл бы и со старой проверкой, то есть не проверял бы
ничего.
"""

from __future__ import annotations

import pytest

from service.infrastructure.cache.redis_manager import is_async_client


class _AsyncLike:
    """Форма `redis.asyncio`, замеренная на живом клиенте: `execute_command` объявлен
    `async def`, а КОМАНДЫ — обычные методы, возвращающие его корутину.

    ⚠️ Асимметрия здесь и есть суть дефекта: `iscoroutinefunction` по команде отвечает
    ЛОЖЬ, по `execute_command` — правду. Двойник, у которого командой был бы `async def`,
    прошёл бы и со старой проверкой, то есть не проверял бы ничего.
    """

    def __init__(self):
        self.calls: list[tuple] = []

    @staticmethod
    async def _done(value):
        return value

    async def execute_command(self, *args, **kwargs):
        return None

    def xtrim(self, stream, **kwargs):
        self.calls.append(("xtrim", stream))
        return self._done(1)

    def scan(self, cursor, match=None, count=None):
        self.calls.append(("scan", match))
        return self._done((0, ["chat:a:stream"]))

    def xinfo_stream(self, stream):
        self.calls.append(("xinfo_stream", stream))
        return self._done({"length": 7})

    def xinfo_groups(self, stream):
        return self._done([])


class _SyncLike:
    """Форма синхронного `redis.Redis`: обычные методы с обычным результатом."""

    def __init__(self):
        self.calls: list[tuple] = []

    def execute_command(self, *args, **kwargs):
        return None

    def xtrim(self, stream, **kwargs):
        self.calls.append(("xtrim", stream))
        return 1

    def scan(self, cursor, match=None, count=None):
        self.calls.append(("scan", match))
        return (0, ["chat:a:stream"])

    def xinfo_stream(self, stream):
        self.calls.append(("xinfo_stream", stream))
        return {"length": 7}

    def xinfo_groups(self, stream):
        return []


def test_the_command_method_cannot_tell_the_clients_apart():
    """🔴 ЗАМЕР, НА КОТОРОМ ДЕРЖИТСЯ ВСЁ ОСТАЛЬНОЕ. Если бы команда различала клиенты,
    прежняя проверка была бы верна и чинить было бы нечего."""
    import inspect

    for name in ("xtrim", "scan", "xinfo_stream"):
        assert not inspect.iscoroutinefunction(getattr(_AsyncLike, name))
        assert not inspect.iscoroutinefunction(getattr(_SyncLike, name))


def test_execute_command_does_tell_them_apart():
    assert is_async_client(_AsyncLike()) is True
    assert is_async_client(_SyncLike()) is False


def test_a_client_without_execute_command_is_not_async():
    """⚠️ Двойник в чужом тесте, заглушка, объект-пустышка — всё это не async-клиент."""
    assert is_async_client(object()) is False
    assert is_async_client(None) is False


@pytest.mark.asyncio
async def test_trimming_actually_runs_on_an_async_client():
    """🔴 ГЛАВНОЕ. Проверяем не флаг, а ФАКТ: команда исполнилась.

    До починки эта же задача возвращала 0 при 112 потоках — молча, без единой ошибки.
    """
    from service.infrastructure.messaging import stream_helpers

    client = _AsyncLike()

    trimmed = await stream_helpers.cleanup_old_streams(client, pattern="chat:*:stream", maxlen=1000)

    assert trimmed == 1, "обрезка не выполнилась"
    assert ("xtrim", "chat:a:stream") in client.calls


@pytest.mark.asyncio
async def test_trimming_also_runs_on_a_sync_client():
    """🔴 ГРАНИЦА. Воркер держит СИНХРОННЫЙ клиент — «чинить» так, чтобы сломать его, нельзя."""
    from service.infrastructure.messaging import stream_helpers

    client = _SyncLike()

    trimmed = await stream_helpers.cleanup_old_streams(client, pattern="chat:*:stream", maxlen=1000)

    assert trimmed == 1
    assert ("xtrim", "chat:a:stream") in client.calls


@pytest.mark.asyncio
async def test_stream_info_is_read_on_an_async_client():
    """До починки отдавало ПУСТО с `'coroutine' object has no attribute 'get'` — то есть
    диагностика потоков была мертва, а выглядела как «потока нет»."""
    from service.infrastructure.messaging import stream_helpers

    info = await stream_helpers.get_stream_info(_AsyncLike(), "chat:a:stream")

    assert info.get("length") == 7, "информация о потоке не прочитана"


@pytest.mark.asyncio
async def test_stream_info_is_read_on_a_sync_client():
    from service.infrastructure.messaging import stream_helpers

    info = await stream_helpers.get_stream_info(_SyncLike(), "chat:a:stream")

    assert info.get("length") == 7


def test_the_rule_lives_in_one_place():
    """⚠️ Две копии правила — ровно тот случай, когда одна отстаёт и ошибка возвращается:
    этот дефект уже чинился в клиенте песочницы, а здесь жил ещё в семи местах.

    Разбираем ДЕРЕВО: подстрока `iscoroutinefunction` осталась бы и в докстринге.
    """
    import ast
    import inspect

    from service.infrastructure.messaging import stream_helpers

    tree = ast.parse(inspect.getsource(stream_helpers))
    misjudging = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "iscoroutinefunction"
    ]

    assert not misjudging, (
        "об асинхронности снова судят по методу — на `redis.asyncio` это ЛОЖЬ для любой "
        "команды, и вызов молча не исполнится"
    )
