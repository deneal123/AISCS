"""Личность ассистентского сообщения ПЕРЕЖИВАЕТ перезагрузку, и по ней виден разрыв.

🔴 Живой разбор диалога упёрся ровно в это: пользователь переключал личности между
сообщениями, а в БД у ответов остались только `usage` и `model_routing`. Логи воркера не
спасают — результат задачи там обрезается по длине, так что у длинного ответа метаданных
не видно вовсе. Состав личности приходилось угадывать по форме ответа.

Сверх отладки запись НЕСУЩАЯ: по ней `persona_switched` узнаёт, что роль сменилась
посреди треда, и просит сайдкар поставить разрыв. Без разрыва новая личность почти не
действует — история с прежним поведением весит больше одной строки инструкции.
"""

from __future__ import annotations

import pytest

from service.services.chat.infrastructure.chat_worker import message_meta


# --------------------------------------------------------------------------- #
# Персист                                                                      #
# --------------------------------------------------------------------------- #
def test_persona_ids_survive_persistence():
    stored = message_meta.persistable_meta({"persona_ids": ["tarot", "analyst"], "usage": {}}, None)

    assert stored["persona_ids"] == ["tarot", "analyst"], (
        "личность не сохранена — какая роль отвечала, узнать будет неоткуда"
    )


def test_persona_order_is_preserved_in_storage():
    """Порядок несущий: первая выбранная — ведущая, её тон и формат получает связка."""
    stored = message_meta.persistable_meta({"persona_ids": ["tarot", "psychologist"]}, None)

    assert stored["persona_ids"] == ["tarot", "psychologist"]


def test_context_report_survives_persistence():
    """🔴 Без него кольцо занятости ИСЧЕЗАЕТ после перезагрузки страницы.

    Фронт ищет последний отчёт в истории сообщений и, не найдя, показывает
    `hasWindow: false` — человек видит пустое место там, где секунду назад был
    показатель, и никакой ошибки при этом нет.
    """
    report = {"window": 128000, "usable": 102904, "used": 1494, "by_section": {"system": 1483}}
    stored = message_meta.persistable_meta({"context": report}, None)

    assert stored["context"] == report


def test_junk_metadata_still_does_not_leak():
    """Расширение белого списка не должно превратить его в «сохраняем всё»."""
    # ⚠️ Пример «мусора» сменён: `context` теперь ПЕРСИСТИТСЯ намеренно (без него кольцо
    # занятости исчезает после перезагрузки страницы). Берём поле, которого в списке нет
    # и быть не должно, — иначе тест закреплял бы уже неверное.
    stored = message_meta.persistable_meta(
        {"persona_ids": ["tarot"], "timings": {"total_ms": 1}}, None
    )

    assert "timings" not in stored, "белый список перестал быть белым списком"


# --------------------------------------------------------------------------- #
# Признак смены роли                                                           #
# --------------------------------------------------------------------------- #
class _FakeRepo:
    """Подмена репозитория: возвращает то, что «лежит» у прошлого ответа треда."""

    def __init__(self, previous):
        self._previous = previous

    async def last_assistant_persona_ids(self, *, db_session, thread_id):
        if isinstance(self._previous, Exception):
            raise self._previous
        return self._previous


@pytest.fixture()
def with_previous(monkeypatch):
    def _install(previous):
        monkeypatch.setattr(message_meta, "ChatWorkerRepository", lambda: _FakeRepo(previous))

    return _install


async def _switched(persona_ids):
    return await message_meta.persona_switched(
        db_session=object(), thread_id="t", persona_ids=persona_ids
    )


@pytest.mark.asyncio
async def test_change_of_role_is_detected(with_previous):
    with_previous(["tarot"])

    assert await _switched(["scientist"]) is True


@pytest.mark.asyncio
async def test_same_role_is_not_a_switch(with_previous):
    with_previous(["tarot"])

    assert await _switched(["tarot"]) is False


@pytest.mark.asyncio
async def test_reordering_is_not_a_switch(with_previous):
    """Перестановка меняет ведущую, но не роли — разрыв тут навредил бы.

    Сказать «предыдущие ответы даны в другой роли», когда роли те же, значит попросить
    модель не держать единый стиль там, где его как раз надо держать.
    """
    with_previous(["psychologist", "tarot"])

    assert await _switched(["tarot", "psychologist"]) is False


@pytest.mark.asyncio
async def test_first_answer_in_thread_is_not_a_switch(with_previous):
    """🔴 `None` (ответов ещё не было) и `[]` (отвечали без личности) — РАЗНОЕ.

    Слить их значит объявить сменой роли первый же ответ в треде и подмешать разрыв
    туда, где сравнивать не с чем.
    """
    with_previous(None)

    assert await _switched(["tarot"]) is False
    assert await _switched([]) is False


@pytest.mark.asyncio
async def test_removing_the_persona_is_a_switch(with_previous):
    """Личность сняли — разрыв нужен: история с ролью никуда не делась."""
    with_previous(["tarot"])

    assert await _switched([]) is True
    assert await _switched(None) is True


@pytest.mark.asyncio
async def test_adding_a_persona_to_a_plain_thread_is_a_switch(with_previous):
    with_previous([])

    assert await _switched(["analyst"]) is True


def test_switch_is_wired_into_the_worker():
    """🔴 ТОЧКА ВЫЗОВА, А НЕ ТОЛЬКО ФУНКЦИЯ.

    В этом проекте уже трижды случалось одно и то же: функция покрыта тестами, мутация
    зелёная — а поломка сидит в МЕСТЕ ВЫЗОВА, потому что тест держал функцию, но не её
    подключение. Признак, который посчитали и не передали, не отличим от отсутствующего.
    """
    import inspect

    from service.services.chat.infrastructure.chat_worker import run_execution

    prepare_src = inspect.getsource(run_execution._prepare_context)
    execute_src = inspect.getsource(run_execution._execute_agent)
    assert "resolve_persona_switched(" in prepare_src, "признак смены роли не считается в воркере"
    assert "persona_switched=prepared.persona_switched" in execute_src, (
        "признак не передан в execute — сайдкар не узнает о смене роли, и разрыва не будет"
    )
    assert "persona_ids=request.persona_ids" in execute_src, "выбор личности не доезжает до движка"


@pytest.mark.asyncio
async def test_read_failure_degrades_to_no_switch(with_previous):
    """Fail-open: лишний разрыв портит ответ заметнее, чем его отсутствие."""
    with_previous(RuntimeError("БД недоступна"))

    assert await _switched(["tarot"]) is False
