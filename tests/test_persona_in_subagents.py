"""Личность донастраивает СУБАГЕНТОВ и аналитиков — не ломая их самостоятельности.

Фаза 2. Здесь же живёт главная ловушка слоя: аналитики модальностей — РАЗДЕЛЯЕМЫЕ
синглтоны, и подмешивать личность к их атрибуту нельзя ни при каких условиях.
"""

from __future__ import annotations

import asyncio

import pytest

from service.domain import persona
from service.domain.persona.lens import PersonaLens
from service.domain.persona.schema import PersonaSpec
from service.domain.subagents import modality_analysts as ma

MARK_IMAGE = "МАРКЕР-ИЗОБРАЖЕНИЕ: считай людей"
MARK_QUERY = "МАРКЕР-ЗАПРОС: ищи статистику"

ANALYST = PersonaSpec(
    id="analyst",
    label="Аналитик",
    core={"identity": "Считаю."},
    slots={
        "analyst.image": MARK_IMAGE,
        "search.query": MARK_QUERY,
        "search.synthesis": "МАРКЕР-СИНТЕЗ: сведи в таблицу",
        "research.plan": "МАРКЕР-ПЛАН: оси метрик",
    },
)


def _lens() -> PersonaLens:
    return PersonaLens([ANALYST])


# --------------------------------------------------------------------------- #
# Аналитики модальностей                                                       #
# --------------------------------------------------------------------------- #
def test_analyst_system_prompt_gets_persona():
    agent = ma.ImageContextAgent()

    with persona.use_persona(_lens()):
        produced = agent._system_for_run()

    assert MARK_IMAGE in produced, "личность не дошла до аналитика изображения"
    assert agent.system_prompt in produced, "базовый промпт аналитика вытеснен"


def test_analyst_prompt_is_unchanged_without_persona():
    """Без личности аналитик работает ровно как раньше — БАЙТ В БАЙТ."""
    agent = ma.ImageContextAgent()

    assert agent._system_for_run() == agent.system_prompt


def test_analyst_slot_is_chosen_by_modality():
    """Слот выбирается по виду материала: аудио-аналитик не берёт image-фрагмент."""
    with persona.use_persona(_lens()):
        image = ma.ImageContextAgent()._system_for_run()
        audio = ma.AudioContextAgent()._system_for_run()

    assert MARK_IMAGE in image
    assert MARK_IMAGE not in audio, "фрагмент чужой модальности утёк в аудио-аналитика"


def test_singleton_analysts_are_never_mutated():
    """🔴 ГЛАВНАЯ ЛОВУШКА СЛОЯ: `_ANALYSTS` — РАЗДЕЛЯЕМЫЕ экземпляры.

    Реестр создаётся на импорте, один объект обслуживает все параллельные запросы
    процесса. Припиши личность к `system_prompt` — и она утечёт в чужой запрос, а при
    повторных вызовах ещё и накопится дублями.
    """
    agent = ma.get_modality_analyst("image")
    before = agent.system_prompt

    with persona.use_persona(_lens()):
        agent._system_for_run()
        agent._system_for_run()  # дважды: мутация накопилась бы повтором

    assert agent.system_prompt == before, "личность записана в РАЗДЕЛЯЕМЫЙ объект"
    assert MARK_IMAGE not in agent.system_prompt


@pytest.mark.asyncio
async def test_analyze_actually_sends_the_persona_prompt(monkeypatch):
    """🔴 Проверяем ТОЧКУ ВЫЗОВА, а не только сборку промпта.

    `_system_for_run()` мог бы существовать и не вызываться — тесты выше остались бы
    зелёными, а модель получала бы промпт без личности. Этот класс промаха («тест держит
    функцию, поломка живёт в месте вызова») на проекте уже случался дважды, поэтому
    смотрим на то, что РЕАЛЬНО ушло в `create_chat_completion`.
    """
    from types import SimpleNamespace

    import service.domain.client as client_mod

    seen: dict = {}

    async def _completion(**kw):
        seen.update(kw)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="итог"))], usage=None
        )

    async def _models():
        return ["acme/chat"]

    monkeypatch.setattr(client_mod, "create_chat_completion", _completion)
    monkeypatch.setattr(client_mod, "list_available_models", _models)
    monkeypatch.setattr(ma, "pick_text_model", lambda _m: "acme/chat")

    with persona.use_persona(_lens()):
        await ma.ImageContextAgent().analyze(user_input="q", name="f.png", content="описание")

    system = next(m["content"] for m in seen["messages"] if m["role"] == "system")
    assert MARK_IMAGE in system, "в модель ушёл промпт БЕЗ личности — точка вызова потеряна"


@pytest.mark.asyncio
async def test_parallel_analysts_do_not_see_each_others_persona():
    """Веер аналитиков: у каждого прогона своя личность, чужая не подмешивается."""
    other = PersonaSpec(
        id="tarot",
        label="Таролог",
        core={"identity": "Символы."},
        slots={"analyst.image": "МАРКЕР-СИМВОЛИКА"},
    )
    seen: dict[str, str] = {}

    async def run(key: str, lens: PersonaLens | None):
        with persona.use_persona(lens):
            await asyncio.sleep(0)
            seen[key] = ma.ImageContextAgent()._system_for_run()

    await asyncio.gather(run("a", _lens()), run("b", PersonaLens([other])), run("none", None))

    assert MARK_IMAGE in seen["a"] and "СИМВОЛИКА" not in seen["a"]
    assert "СИМВОЛИКА" in seen["b"] and MARK_IMAGE not in seen["b"]
    assert seen["none"] == ma.ImageContextAgent().system_prompt


# --------------------------------------------------------------------------- #
# Субагенты и общие точки                                                      #
# --------------------------------------------------------------------------- #
def test_subagent_helper_wraps_and_stays_neutral():
    # Берём НАСТОЯЩЕГО субагента, а не заглушку: хелперы живут на `BaseSubAgent`, и
    # тест на минимальном наследнике не доказал бы, что они доступны там, где нужны.
    from service.domain.subagents.web_search import WebSearchAgent

    agent = WebSearchAgent({"model": "m"})
    base = "Базовый промпт."

    assert agent.persona_wrap(base, "search.query") is base
    with persona.use_persona(_lens()):
        assert MARK_QUERY in agent.persona_wrap(base, "search.query")
        assert agent.persona_fragment("search.query") == MARK_QUERY


def test_standalone_query_prompt_gets_persona():
    """Переформулировка запроса — общая точка поиска, ресерча и картинки."""
    from service.domain.subagents.context_query import _CONDENSE_SYSTEM, _persona_condense_system

    assert _persona_condense_system() == _CONDENSE_SYSTEM
    with persona.use_persona(_lens()):
        assert MARK_QUERY in _persona_condense_system()


def test_research_prompts_get_persona():
    from service.domain.tools.deep_research import _wrap

    assert _wrap("Промпт", "research.plan") == "Промпт"
    with persona.use_persona(_lens()):
        assert "МАРКЕР-ПЛАН" in _wrap("Промпт", "research.plan")


# --------------------------------------------------------------------------- #
# Куда личность НЕ идёт                                                        #
# --------------------------------------------------------------------------- #
def test_verbatim_and_translation_prompts_stay_clean():
    """🔴 Дословная транскрипция и ПЕРЕВОД отчёта личности не подлежат.

    Персонализировать транскрипт — исказить фидельность; стилизовать перевод — превратить
    его в пересказ. Это проектное решение, а не «ещё не подключили», поэтому оно
    проверяется: тексты этих промптов обязаны оставаться литералами без обёрток.
    """
    import inspect

    from service.domain.subagents import audio_transcribe, deep_research

    for module in (audio_transcribe, deep_research):
        src = inspect.getsource(module)
        assert "persona_wrap" not in src, f"{module.__name__}: личность подмешана"
        assert "persona_fragment" not in src, f"{module.__name__}: личность подмешана"


def test_router_prompt_is_persona_free():
    """Маршрут и цена запроса обязаны остаться детерминированными."""
    import inspect

    from service.domain.routing import auto_prompt
    from service.domain.tools import router

    # ⚠️ `constants` (категорийный роутер) удалён вместе с самим роутером; его место в
    # проверке занял промпт оркестратора — теперь маршрут решает он.
    for module in (router, auto_prompt):
        src = inspect.getsource(module)
        assert "persona" not in src.lower(), f"{module.__name__}: личность влияет на маршрут"
