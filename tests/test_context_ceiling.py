"""Страховочная сетка жертвует МЕНЕЕ приоритетным, а не самым крупным.

⚠️ Почему это вообще важно. Вложение текущей задачи почти всегда крупнейшее из
присутствующего — документ на сотню килобайт против пары абзацев recall'а. Пока сетка
выбирала жертву как ``max(sections, key=tokens)``, она систематически била именно по
нему, хотя ``SECTION_PRIORITY`` ставит вложения вторыми после фактов. Наблюдаемое
следствие: пользователь приложил файл, а модель отвечает «не вижу вложение».

Как тесты загоняют код в сетку: бюджет подменяется на такой, где ДОЛИ секций в сумме
больше, чем ``usable``. Каждая секция честно влезает в свою долю, а вместе они не
влезают в потолок — ровно то расхождение, ради которого сетка и существует.
"""

from __future__ import annotations

import pytest

from service.domain.pipeline import context_assembler as ca
from service.domain.pipeline.context_budget import ContextBudget
from service.settings import config


def _budget(usable: int, sections: dict[str, int]) -> ContextBudget:
    return ContextBudget(
        window=8000,
        usable=usable,
        output_reserve=0,
        prompt_overhead=0,
        sections=sections,
    )


async def _assemble(monkeypatch, *, usable, sections, **kw):
    """Собрать контекст на подменённом бюджете, без сжатия — сетка на чистой обрезке."""

    async def _fake_budget(**_kw):
        return _budget(usable, sections)

    monkeypatch.setattr(ca, "compute_budget", _fake_budget)
    return await ca.assemble_context(
        model_id="m1", config=config, user_input="вопрос", compressor=None, **kw
    )


@pytest.mark.asyncio
async def test_ceiling_spares_attachment_and_cuts_low_priority(monkeypatch):
    """Вложение (крупное, приоритетное) уцелело, память (мелкая, последняя) урезана.

    Мутация «вернуть max(sections, key=tokens)» обязана покраснеть: старый код резал бы
    именно files, потому что он тут вдвое больше memory.
    """
    assembled = await _assemble(
        monkeypatch,
        usable=1200,
        sections={"files": 800, "memory": 400},
        files="текст вложения " * 4000,
        memory="выдержка из памяти " * 4000,
    )

    files = assembled.by_section.get("files", 0)
    memory = assembled.by_section.get("memory", 0)

    assert files > memory, (
        f"вложение ужато до {files} при памяти {memory} — сетка порезала приоритетное"
    )
    assert files >= 700, f"вложение потеряло {800 - files} токенов, хотя резать надо память"
    assert assembled.used <= assembled.budget.usable, "потолок не удержан"


@pytest.mark.asyncio
async def test_ceiling_cuts_history_before_attachment(monkeypatch):
    """История уступает вложению: она ниже в SECTION_PRIORITY."""
    assembled = await _assemble(
        monkeypatch,
        usable=1200,
        sections={"files": 700, "history": 700},
        files="текст вложения " * 4000,
        history=[{"role": "user", "content": "реплика диалога " * 200} for _ in range(4)],
    )

    assert assembled.by_section.get("files", 0) >= 600, "вложение порезано вперёд истории"
    assert assembled.used <= assembled.budget.usable, "потолок не удержан"


@pytest.mark.asyncio
async def test_ceiling_holds_when_everything_overflows(monkeypatch):
    """Переполнение по всем секциям сразу: потолок обязан удержаться.

    Проверяет, что цикл жертв доходит до конца, а не срезает одну секцию и сдаётся.
    """
    assembled = await _assemble(
        monkeypatch,
        usable=900,
        sections={"files": 800, "memory": 800, "knowledge": 800, "summary": 800},
        files="вложение " * 3000,
        memory="память " * 3000,
        knowledge="знания " * 3000,
        summary="резюме " * 3000,
    )

    assert assembled.used <= assembled.budget.usable, (
        f"после сетки {assembled.used} > {assembled.budget.usable}"
    )
    # Приоритетное не должно исчезнуть целиком ради менее важного.
    assert assembled.by_section.get("files", 0) > 0, "вложение вырезано полностью"


@pytest.mark.asyncio
async def test_ceiling_untouched_when_it_fits(monkeypatch):
    """Влезли — сетка не трогает ничего.

    ⚠️ Без этого теста «сетка» могла бы резать всегда и остальные тесты этого не
    заметили бы: они проверяют только верхнюю границу.

    ⚠️ Проверяем ДОСЛОВНОЕ наличие текста, а не отсутствие пометки об обрезке: на
    коротких строках обрезка не оставляет пометки вовсе (маркер длиннее самого куска),
    и мутация «резать всегда» проходила мимо такого утверждения незамеченной.
    """
    files_text = "короткое вложение, которое обязано доехать до модели целиком"
    memory_text = "короткая память, тоже целиком"

    assembled = await _assemble(
        monkeypatch,
        usable=6000,
        sections={"files": 2000, "memory": 2000},
        files=files_text,
        memory=memory_text,
    )

    assert files_text in assembled.system_context, "вложение обрезано, хотя влезало"
    assert memory_text in assembled.system_context, "память обрезана, хотя влезала"
