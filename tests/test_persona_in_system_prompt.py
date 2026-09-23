"""Личность доезжает до СИСТЕМНОГО ПРОМПТА — и не ломает всё остальное.

Фаза 1: секция «Специализация» появляется в `messages[0]`, у неё СВОЙ бюджет, а без
активной личности промпт собирается байт-в-байт как раньше.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from service.domain import persona
from service.domain.persona.lens import SECTION_TITLE, PersonaLens
from service.domain.persona.schema import PersonaSpec
from service.domain.subagents.general import GeneralAgent
from service.schemas.agents import UserContext

ANALYST = PersonaSpec(
    id="analyst",
    label="Аналитик",
    core={"identity": "МАРКЕР-ЛИЧНОСТИ: считаю всё измеримое.", "tone": "сухо"},
)


def _ctx(**kw) -> UserContext:
    return UserContext(user_id="", request_time=datetime.now(UTC), **kw)


def _agent() -> GeneralAgent:
    return GeneralAgent({"model": "test-model"})


def test_prompt_is_byte_identical_without_persona():
    """🔴 ГЛАВНЫЙ ИНВАРИАНТ ФАЗЫ: без личности системный промпт НЕ изменился.

    Сравниваем сборку вне области действия личности с ручной склейкой по прежнему
    правилу (`instructions[:3000]` + `system_context`). Разойдись они хоть пробелом —
    изменился бы промпт всего текущего трафика.
    """
    agent = _agent()
    ctx = _ctx(system_context="## Факты о пользователе\nЛюбит краткость.")

    produced = agent._compose_system_instructions(ctx)
    expected = f"{agent.instructions[:3000]}\n\n{ctx.system_context}"

    assert produced == expected


def test_prompt_without_context_is_just_instructions():
    agent = _agent()

    assert agent._compose_system_instructions(_ctx()) == agent.instructions[:3000]


def test_persona_section_appears_in_prompt():
    """Активная личность добавляет именованную секцию и свой текст."""
    agent = _agent()

    with persona.use_persona(PersonaLens([ANALYST])):
        produced = agent._compose_system_instructions(_ctx())

    assert SECTION_TITLE in produced, "секция личности не попала в системный промпт"
    assert "МАРКЕР-ЛИЧНОСТИ" in produced
    # Инвариантная часть базового промпта обязана уцелеть: личность замещает СТИЛЬ,
    # а не рабочую процедуру. Проверяем именно её, а не префикс `instructions` —
    # первая строка как раз и есть замещаемая идентичность.
    assert "Режим работы:" in produced, "базовые инструкции агента вытеснены"
    assert "Работа с приложенными файлами:" in produced


def test_persona_replaces_base_style_and_leaves_the_rest():
    """🔴 Стилевые строки базы УБИРАЮТСЯ, когда есть личность.

    Живой прогон: все ответы под личностями начинались словами «Краткий вывод:» —
    дословно из базовой строки про markdown, — а рядом стояли ДВЕ строки «Тон:» с
    несовместимым содержанием. Приписанная секция базу не перекрывала.
    """
    agent = _agent()
    style_line = "Тон: уверенный, деловой, дружелюбный"
    format_line = "краткий вывод → детали → следующие шаги"

    plain = agent._compose_system_instructions(_ctx())
    assert style_line in plain, "без личности базовый стиль обязан остаться на месте"
    assert format_line in plain

    with persona.use_persona(PersonaLens([ANALYST])):
        produced = agent._compose_system_instructions(_ctx())

    assert style_line not in produced, "базовый тон уцелел — он перебьёт тон личности"
    assert format_line not in produced, "базовый формат уцелел — он перебьёт формат личности"
    assert produced.count("Тон:") == 1, "в промпте больше одной строки «Тон:» — это спор"


def test_persona_overrides_are_real_substrings():
    """🔴 Замена ПОДСТРОКОЙ: ключ, которого нет в промпте, молча ничего не делает.

    Без этого стража правка `GENERAL_PROMPT` разоружила бы механизм, и заметить это
    можно было бы только по качеству ответов — тот же класс отказов, ради которого
    словарь слотов личности сделан закрытым.
    """
    from service.domain.subagents.general import GENERAL_PROMPT, PERSONA_OVERRIDES

    assert PERSONA_OVERRIDES, "список замен пуст — личность больше ничего не замещает"
    for old, _new in PERSONA_OVERRIDES:
        assert old in GENERAL_PROMPT, f"замещаемого куска нет в промпте: {old!r}"


def test_base_style_is_untouched_for_agents_without_overrides():
    """Прочие агенты личность не замещает: у них базовый промпт — процедура, а не стиль."""
    from service.domain.base import SimpleStreamingAgent

    assert SimpleStreamingAgent.persona_overrides == ()


def test_persona_reaches_messages_zero():
    """Промпт обязан доехать до `messages[0]` — там его видит модель."""
    agent = _agent()

    with persona.use_persona(PersonaLens([ANALYST])):
        messages = agent._build_messages("вопрос", _ctx())

    assert messages[0]["role"] == "system"
    assert "МАРКЕР-ЛИЧНОСТИ" in messages[0]["content"]


def test_persona_has_its_own_budget_and_cannot_evict_instructions():
    """🔴 Длинная личность режется СВОИМ бюджетом, а не за счёт инструкций.

    Раньше здесь была одна слепая обрезка на всё; если бы личность попала под неё,
    она вытеснила бы хвост инструкций агента — молча и только на персонифицированных
    запросах.
    """
    agent = _agent()
    huge = PersonaSpec(id="huge", label="Огромная", core={"identity": "Я " + "очень " * 5000})

    with persona.use_persona(PersonaLens([huge])):
        produced = agent._compose_system_instructions(_ctx())

    # Сравниваем с инструкциями ПОСЛЕ замещения стиля: замещение — отдельное правило,
    # его держит `test_persona_replaces_base_style_and_leaves_the_rest`. Здесь речь
    # только про то, что личность не съедает чужой бюджет.
    with persona.use_persona(PersonaLens([huge])):
        base = agent._base_instructions()
    assert base in produced, "инструкции агента обрезаны личностью"
    # Секция ужата: без бюджета она была бы в разы длиннее самих инструкций.
    section_len = len(produced) - len(base)
    assert section_len < len(huge.core.identity), "секция личности не ужата своим бюджетом"


@pytest.mark.asyncio
async def test_context_overhead_grows_with_persona():
    """Резерв под системный промпт обязан расти вместе с личностью.

    Иначе бюджет считает, что промпт короче, чем он есть, и секция «Специализация»
    молча съедает место, отведённое ВЛОЖЕНИЯМ пользователя.
    """
    from service.domain.pipeline import context_budget
    from service.settings import config

    async def _window(_model, _cfg):
        return 128_000, True

    original = context_budget.resolve_window
    context_budget.resolve_window = _window
    try:
        plain = await context_budget.compute_budget(model_id="m", config=config)
        with persona.use_persona(PersonaLens([ANALYST])):
            with_persona = await context_budget.compute_budget(model_id="m", config=config)
    finally:
        context_budget.resolve_window = original

    assert with_persona.usable < plain.usable, (
        "резерв под системный промпт не вырос — личность съест место вложений"
    )
