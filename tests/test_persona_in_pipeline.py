"""Личность в работе с контекстом: сжатие и декомпозиция.

Фаза 3. Главное здесь — не «работает ли впрыск», а ГДЕ ИМЕННО он происходит: сжатие
устроено как map-reduce, и разница между «в reduce» и «в каждый кусок» — это разница в
цене на самых дорогих запросах.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from service.domain import persona
from service.domain.persona.lens import PersonaLens
from service.domain.persona.schema import PersonaSpec
from service.domain.pipeline import context_compressor as cc
from service.domain.pipeline import decomposition as dec

MARK_COMPRESS = "МАРКЕР-СЖАТИЕ: числа не терять"
MARK_DECOMPOSE = "МАРКЕР-ДЕКОМПОЗИЦИЯ: отделяй сбор от интерпретации"

ANALYST = PersonaSpec(
    id="analyst",
    label="Аналитик",
    core={"identity": "Считаю."},
    slots={"compression": MARK_COMPRESS, "decomposition": MARK_DECOMPOSE},
)


def _lens() -> PersonaLens:
    return PersonaLens([ANALYST])


def _resp(text: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=None
    )


@pytest.fixture
def capture_compression(monkeypatch):
    """Перехватываем ВСЕ вызовы сжатия и запоминаем их системные промпты."""
    systems: list[str] = []

    async def _completion(**kw):
        systems.append(next(m["content"] for m in kw["messages"] if m["role"] == "system"))
        # Сводка ДЛИННАЯ намеренно: короткая уложилась бы в бюджет, reduce не запустился
        # бы вовсе, и сквозной тест молча проверял бы только map-фазу.
        return _resp("Сводка куска с числами 42 и 7. " * 20)

    import service.domain.client as client_mod

    monkeypatch.setattr(client_mod, "create_chat_completion", _completion)
    monkeypatch.setattr(cc, "_pick_model", lambda: _async("acme/chat"))
    return systems


def _async(value):
    async def _inner():
        return value

    return _inner()


@pytest.mark.asyncio
async def test_persona_reaches_reduce_step(capture_compression):
    """Личность обязана дойти до reduce — там решается, ЧТО сохранить при нехватке места."""
    with persona.use_persona(_lens()):
        await cc._summarize("текст", 100, "files", None, "acme/chat", personalized=True)

    assert MARK_COMPRESS in capture_compression[0]


@pytest.mark.asyncio
async def test_map_step_stays_persona_free(capture_compression):
    """🔴 ЦЕНА: в map-куски личность НЕ идёт.

    `_summarize` зовётся на КАЖДЫЙ кусок: до 12 на секцию, три секции — до 39 вызовов на
    один запрос пользователя. Личность в system каждого из них умножилась бы на 39 ровно
    там, где запрос и без того самый дорогой (большое вложение). На reduce вызов ОДИН, а
    решает он то же самое.
    """
    with persona.use_persona(_lens()):
        await cc._summarize("кусок", 100, "files", None, "acme/chat")  # без personalized

    assert MARK_COMPRESS not in capture_compression[0], (
        "личность попала в map-шаг — цена умножится на число кусков"
    )


@pytest.mark.asyncio
async def test_full_compression_personalizes_only_the_last_call(capture_compression, monkeypatch):
    """🔴 СКВОЗНОЙ ПРОГОН: проверяем ТОЧКУ ВЫЗОВА, а не только флаг.

    Тесты выше зовут `_summarize` напрямую и не заметили бы, что `compress_to_budget`
    перестал передавать `personalized=True`. Этот класс промаха («тест держит функцию,
    поломка живёт в месте вызова») за сессию всплыл трижды, поэтому гоняем настоящий
    map-reduce и смотрим на РАСПРЕДЕЛЕНИЕ личности по вызовам: во всех map-кусках её быть
    не должно, в последнем (reduce) — обязана.
    """
    # Куски режутся по абзацам и по 6000 токенов — берём заведомо больше двух кусков,
    # иначе reduce не запустится и тест ничего не проверит (страховка ниже).
    monkeypatch.setattr(cc, "_CHUNK_TOKENS", 200)
    para = "Данные строки отчёта: выручка 42, маржа 7. " * 30
    long_text = ("\n\n").join(para for _ in range(6))

    with persona.use_persona(_lens()):
        await cc.compress_to_budget(long_text, 60, kind="files")

    assert len(capture_compression) > 1, "map-reduce не случился — тест ничего не проверяет"
    map_calls, reduce_call = capture_compression[:-1], capture_compression[-1]

    assert all(MARK_COMPRESS not in s for s in map_calls), (
        f"личность попала в {sum(MARK_COMPRESS in s for s in map_calls)} map-кусков — цена умножилась"
    )
    assert MARK_COMPRESS in reduce_call, "reduce потерял личность (точка вызова)"


@pytest.mark.asyncio
async def test_compression_is_unchanged_without_persona(capture_compression):
    """Без личности промпт сжатия прежний даже на reduce."""
    await cc._summarize("текст", 100, "files", None, "acme/chat", personalized=True)

    assert capture_compression[0] == cc._PROMPTS.get("files", cc._DEFAULT_PROMPT)


@pytest.mark.asyncio
async def test_decomposition_prompt_gets_persona(monkeypatch):
    """Как дробить составной запрос — часть специализации. Вызов ОДИН, цена не множится."""
    seen: dict = {}

    async def _completion(**kw):
        seen.update(kw)
        return _resp('{"subtasks": []}')

    import service.domain.client as client_mod

    monkeypatch.setattr(client_mod, "create_chat_completion", _completion)

    assert dec._persona_decompose_prompt() == dec._decompose_prompt()
    with persona.use_persona(_lens()):
        assert MARK_DECOMPOSE in dec._persona_decompose_prompt()


def test_graph_slot_is_absent_from_vocabulary():
    """🔴 `graph.query` НЕ объявлен — и это решение, а не пропуск.

    Обе точки обращения к графу его не принимают: `search_knowledge_graph` формулирует
    вопрос моделью (у неё личность уже в системном промпте), а `_auto_knowledge` шлёт
    запрос в СЕМАНТИЧЕСКИЙ поиск как есть — дописывание инструкции туда загрязняет вектор
    и УХУДШАЕТ выдачу. Слот-пустышка был бы «редактируемым no-op».
    """
    from service.domain.persona import slots

    assert "graph.query" not in slots.SLOTS
