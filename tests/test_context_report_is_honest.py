"""Отчёт о занятости контекста считает ТО, что реально уходит в модель.

🔴 Живой замер: на пустом треде отчёт показывал `used: 14` при реальном промпте в 1123
токена — кольцо занятости рисовало ноль там, где килотокен уже потрачен. Причина не в
арифметике: `used` складывался только из собранных СЕКЦИЙ (запрос, история, вложения), а
базовые инструкции агента, секция личности и схемы инструментов в него не входили вовсе.

Это два независимых счётчика — ассемблер считал своё, промпт собирался в другом месте, —
и разъехались они ровно так, как такие пары и разъезжаются. Поэтому постоянную часть
меряет САМ АГЕНТ (`fixed_prompt_tokens`) из тех же кусков, что уходят в `messages[0]` и
в поле `tools`.

⚠️ Направление остаточной ошибки — то же, что у оценщика токенов: отчёт обязан ЗАВЫШАТЬ.
Кольцо предупреждает о переполнении окна; предупредить рано не страшно, поздно — поздно.
"""

from __future__ import annotations

import pytest

from service.domain.persona.lens import PersonaLens
from service.domain.persona.schema import PersonaSpec
from service.domain.pipeline.context_assembler import assemble_context
from service.domain.subagents.general import GeneralAgent
from service.settings import config

PERSONA = PersonaSpec(id="p", label="П", core={"identity": "Считаю всё измеримое.", "tone": "сухо"})


@pytest.mark.asyncio
async def test_fixed_part_is_counted_in_used():
    """🔴 ГЛАВНОЕ: постоянная часть промпта входит в занятость."""
    without = await assemble_context(model_id="m", config=config, user_input="привет")
    with_fixed = await assemble_context(
        model_id="m", config=config, user_input="привет", fixed_tokens=1500
    )

    assert with_fixed.used - without.used == 1500
    assert with_fixed.by_section["system"] == 1500


@pytest.mark.asyncio
async def test_fixed_part_is_a_separate_line_in_the_breakdown():
    """Отдельной строкой, а не растворить: на коротком диалоге ЭТО и есть весь контекст."""
    assembled = await assemble_context(
        model_id="m", config=config, user_input="привет", fixed_tokens=1500
    )

    assert assembled.by_section["system"] == 1500
    assert assembled.as_meta()["by_section"]["system"] == 1500


@pytest.mark.asyncio
async def test_zero_fixed_part_leaves_the_report_untouched():
    """Агент не умеет себя измерить → отчёт как раньше, без пустой секции."""
    assembled = await assemble_context(model_id="m", config=config, user_input="привет")

    assert "system" not in assembled.by_section


def test_agent_measures_its_own_constant_part():
    """Меряет САМ агент — из тех же кусков, что уходят в промпт и в поле `tools`.

    ⚠️ Сравниваем ДВЕ личности разного размера, а не «с личностью против без».
    С активной личностью базовый промпт СОКРАЩАЕТСЯ заменами (`PERSONA_OVERRIDES`), и у
    короткой личности итог получается меньше, чем совсем без неё — это верное поведение,
    а не потеря секции.
    """
    from service.domain import persona

    agent = GeneralAgent({"model": "m"})
    big = PersonaSpec(
        id="big",
        label="Большая",
        core={"identity": "Очень подробное описание роли. " * 20, "tone": "сухо"},
    )

    assert agent.fixed_prompt_tokens() > 0, "постоянная часть не посчитана — отчёт покажет ноль"

    with persona.use_persona(PersonaLens([PERSONA])):
        small_persona = agent.fixed_prompt_tokens()
    with persona.use_persona(PersonaLens([big])):
        big_persona = agent.fixed_prompt_tokens()

    assert big_persona > small_persona, "секция личности не учтена, а она уезжает каждым запросом"


def test_tools_schemas_are_counted():
    """Схемы инструментов едут полем `tools`, но окно занимают наравне с текстом.

    Замер: 416 токенов из 1123 — самая крупная часть после инструкций.
    """
    from service.domain.tools.function_tools import DEFAULT_FUNCTION_TOOLS
    from service.shared.token_budget import estimate_tokens

    with_tools = GeneralAgent({"model": "m"})
    without_tools = GeneralAgent({"model": "m"})
    without_tools.tools = []

    assert DEFAULT_FUNCTION_TOOLS, "у general нет инструментов — тест проверял бы пустоту"
    delta = with_tools.fixed_prompt_tokens() - without_tools.fixed_prompt_tokens()
    assert delta > estimate_tokens("x" * 400), "схемы инструментов в занятость не попали"
