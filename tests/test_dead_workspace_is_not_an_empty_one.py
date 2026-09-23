"""Мёртвая песочница — это НЕ пустой каталог.

🔴 НАЙДЕНО ЖИВЫМ ПРОГОНОМ. Обращение к пропавшей песочнице отдавало `None`, дерево из
`None` — пустой список, и панель писала «Каталог пуст». Человек видел не ошибку, а ЛОЖЬ О
СВОИХ ФАЙЛАХ: они были, а сообщение утверждало обратное — и искать было негде.

⚠️ Случай НЕ РЕДКИЙ. Реестр сайдкара живёт в памяти: его перезапуск обнуляет все песочницы
разом, а ключи привязок в Redis живут ещё до получаса. Всё это время каждый ход честно
поднимает файловые инструменты, и каждый их вызов отвечает «песочницы нет». Поэтому
доказанно мёртвую привязку мало НАЗВАТЬ — её надо СТЕРЕТЬ, и с обеих сторон: из панели и
из воркера (снимок после хода — единственная проверка живости, которая случается всегда).
"""

from __future__ import annotations

import pytest

from service.infrastructure import workspace_client as wc


class _Response:
    def __init__(self, status: int, payload: dict | None = None):
        self.status_code = status
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class _Client:
    """httpx-клиент, отвечающий заданным кодом."""

    def __init__(self, status: int, payload: dict | None = None):
        self._response = _Response(status, payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *_args, **_kwargs):
        return self._response


@pytest.fixture
def sidecar(monkeypatch):
    """Подменяет транспорт клиента песочницы на ответ с заданным кодом."""

    def _install(status: int, payload: dict | None = None):
        monkeypatch.setattr(wc.httpx, "AsyncClient", lambda **_kw: _Client(status, payload))

    monkeypatch.setattr(wc, "_config", lambda: (True, "http://workspace:8080", 5.0, "key", 1800.0))
    return _install


REF = {
    "workspace_id": "w-1",
    "token": "t",
    "user_id": "u-1",
    "root": "/workspace",
    # Ссылка знает СВОЙ тред: стирать привязку надо по нему, а тащить его отдельным
    # аргументом сквозь весь путь обработки хода — четыре подписи ради одной строки.
    "thread_id": "t-9",
}


@pytest.mark.asyncio
async def test_a_vanished_workspace_is_named_not_swallowed(sidecar):
    """⚠️ ГЛАВНОЕ. 404 от сайдкара — определённый ответ «такой песочницы нет»."""
    sidecar(404, {"error": "not_found", "detail": "песочница w-1 не найдена или истекла"})

    with pytest.raises(wc.WorkspaceGone):
        await wc.tree(REF)


@pytest.mark.asyncio
async def test_temporary_sidecar_failure_keeps_the_binding(sidecar):
    """502 — это временная недоступность, а не доказательство смерти песочницы.

    502 значит «сайдкару поплохело», а не «песочницы нет»: привязку стирать нельзя, ответ
    пользователю нельзя подменять пустым каталогом. Привязка остаётся для повторной попытки.
    """
    sidecar(502, {"error": "driver_failed"})

    with pytest.raises(wc.WorkspaceUnavailable):
        await wc.tree(REF)


@pytest.mark.asyncio
async def test_a_refused_token_is_not_a_vanished_workspace(sidecar):
    """403 — «токен не подошёл». Стереть привязку тут значило бы выбрасывать ЖИВУЮ песочницу."""
    sidecar(403, {"error": "forbidden"})

    assert await wc.read_file(REF, "a.txt") is None


@pytest.mark.asyncio
async def test_a_missing_file_does_not_erase_a_live_workspace(sidecar):
    """A nested 404 proves only that the requested file is absent."""

    sidecar(404, {"error": "not_found", "detail": "file not found"})

    assert await wc.read_file(REF, "missing.txt") is None


@pytest.mark.asyncio
async def test_the_panel_says_expired_and_forgets_the_binding(sidecar, monkeypatch):
    """🔴 ЧТО ВИДИТ ЧЕЛОВЕК: «истекла» (410), а не «Каталог пуст» (200 с пустым списком)."""
    from fastapi import HTTPException

    from service.services.chat.presentation.routers.chat_api import workspace_api as api

    sidecar(404, {"error": "not_found"})
    forgotten: list[str] = []
    monkeypatch.setattr(
        api.workspace_client,
        "forget_binding",
        lambda _redis, thread_id: _record(forgotten, thread_id),
    )

    with pytest.raises(HTTPException) as caught:
        async with api._alive(None, "t-1"):
            await wc.tree(REF)

    assert caught.value.status_code == 410, "смерть песочницы выдана за что-то другое"
    assert "истекла" in str(caught.value.detail)
    assert forgotten == ["t-1"], "тред остался привязан к песочнице, которой нет"


@pytest.mark.asyncio
async def test_the_panel_keeps_binding_when_sidecar_is_temporarily_unavailable(
    sidecar, monkeypatch
):
    from fastapi import HTTPException

    from service.services.chat.presentation.routers.chat_api import workspace_api as api

    sidecar(503, {"error": "driver_failed"})
    forgotten: list[str] = []
    monkeypatch.setattr(
        api.workspace_client,
        "forget_binding",
        lambda _redis, thread_id: _record(forgotten, thread_id),
    )

    with pytest.raises(HTTPException) as caught:
        async with api._alive(None, "t-1"):
            await wc.tree(REF)

    assert caught.value.status_code == 503
    assert forgotten == []


async def _record(sink: list, value):
    sink.append(value)


@pytest.mark.asyncio
async def test_a_healthy_call_passes_through_untouched(sidecar):
    """Живая песочница через тот же проход обязана проходить без единой помехи."""
    from service.services.chat.presentation.routers.chat_api import workspace_api as api

    sidecar(200, {"entries": [{"path": "/workspace/a.txt", "size": 3}]})

    async with api._alive(None, "t-1"):
        entries = await wc.tree(REF)

    assert entries == {"entries": [{"path": "/workspace/a.txt", "size": 3}]}


@pytest.mark.asyncio
async def test_the_worker_forgets_the_binding_after_the_turn(sidecar, monkeypatch):
    """🔴 ВТОРАЯ СТОРОНА. Панель могут не открыть НИКОГДА — тогда лечит только воркер.

    Снимок делается после КАЖДОГО хода, поэтому он и есть проверка живости. Узнав правду,
    он обязан стереть привязку: иначе следующий ход снова пойдёт к мёртвой песочнице.
    """
    from service.services.chat.infrastructure.chat_worker import artifacts

    sidecar(404, {"error": "not_found"})
    forgotten: list[str] = []
    monkeypatch.setattr(
        artifacts, "_forget_dead_binding", lambda thread_id: _record(forgotten, thread_id)
    )

    await artifacts.snapshot_workspace({"workspace_ref": REF}, "посчитай")

    assert forgotten == ["t-9"], (
        "тред остался привязан к пропавшей песочнице — до получаса каждый ход будет "
        "поднимать файловые инструменты, и каждый их вызов отвечать «песочницы нет»"
    )


@pytest.mark.asyncio
async def test_the_snapshot_still_never_breaks_the_reply(sidecar, monkeypatch):
    """⚠️ Лечение не отменяет best-effort: сбой снимка ответ пользователю не роняет."""
    from service.services.chat.infrastructure.chat_worker import artifacts

    def _boom(**_kw):
        raise RuntimeError("сайдкар лёг")

    monkeypatch.setattr(wc, "_config", lambda: (True, "http://workspace:8080", 5.0, "k", 1800.0))
    monkeypatch.setattr(wc.httpx, "AsyncClient", _boom)

    await artifacts.snapshot_workspace({"workspace_ref": REF}, "посчитай")


@pytest.mark.asyncio
async def test_the_binding_carries_its_own_thread(monkeypatch):
    """🔴 БЕЗ ЭТОГО ЛЕЧЕНИЕ МЕРТВО. Стирать привязку нечем, если ссылка не знает своего треда.

    Проверяем ОБА пути выдачи ссылки — и второй важнее. ⚠️ Привязка, лежащая в Redis
    СЕЙЧАС, сохранена кодом БЕЗ этого поля и живёт ещё до получаса: разворот такого словаря
    поля не добавит, и ровно у тех тредов, что уже работают, лечение не сработает. Поэтому
    переиспользование проверяем на СТАРОЙ привязке, а не на только что сохранённой своей —
    иначе тест зелен от того, что поле в неё положил предыдущий шаг того же теста.
    """
    saved: dict = {}
    monkeypatch.setattr(wc, "_config", lambda: (True, "http://ws:8080", 5.0, "k", 1800.0))
    monkeypatch.setattr(
        wc, "_create", lambda *a, **k: _value({"workspace_id": "w-7", "token": "tok"})
    )
    monkeypatch.setattr(wc, "_read_binding", lambda *a: _value(saved.get("ref")))
    monkeypatch.setattr(wc, "_save_binding", lambda _r, _t, ref, _ttl: _store(saved, ref))

    fresh = await wc.ensure_workspace(None, "t-42", "u-1")
    assert fresh["thread_id"] == "t-42", "новая песочница не помнит, чьей она стала"

    # Привязка ПРЕЖНЕГО формата: такие лежат в Redis прямо сейчас.
    saved["ref"] = {"workspace_id": "w-7", "token": "tok", "root": "/workspace"}
    reused = await wc.ensure_workspace(None, "t-42", "u-1")

    assert reused["workspace_id"] == "w-7", "переиспользования не случилось — тест не о том"
    assert reused["thread_id"] == "t-42", "ссылка из старой привязки не знает своего треда"


async def _value(payload):
    return payload


async def _store(sink: dict, ref: dict):
    sink["ref"] = dict(ref)
