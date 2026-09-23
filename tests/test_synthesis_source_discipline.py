"""Синтез разделяет «сказал пользователь» и «подтверждено источниками».

🔴 ЖИВАЯ ЖАЛОБА. На запрос «сделай досье: X училась в вузе, работает в банке неофициально
как вендор» отчёт подал эти утверждения как УСТАНОВЛЕННЫЕ ФАКТЫ о названном лице и
построил на них раздел «репутационные риски» — при том что источники ничего подобного не
содержали, а сам отчёт признавал нехватку данных. Досье на конкретных людей с
недоказанными утверждениями — риск и репутационный, и правовой.

Синтез обязан помечать фактом лишь то, что подтверждают источники; вводные из запроса —
это гипотезы для проверки. Правило живёт в ОДНОМ месте (`web_search._SOURCE_DISCIPLINE`)
и одинаково применяется на обоих путях синтеза — веб-поиск и глубокий ресёрч, — иначе
один режим начнёт выдавать вводные за факт, а другой нет.
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap

from service.domain.subagents.web_search import _SOURCE_DISCIPLINE, _SYNTHESIS_PROMPT
from service.domain.tools.deep_research import _SYNTHESIS_PROMPT as DR_PROMPT


def _has_rule(text: str) -> bool:
    low = text.lower()
    return "подтверждено источник" in low and ("не подтверждается" in low or "непроверен" in low)


def test_web_search_prompt_carries_the_rule():
    assert _has_rule(_SYNTHESIS_PROMPT), "правило дисциплины источников выпало из web_search"


def test_deep_research_prompt_carries_the_rule():
    # DR_PROMPT — шаблон с {topic}/{data}; проверяем на заполненном виде.
    filled = DR_PROMPT.format(topic="тема", data="данные")
    assert _has_rule(filled), "правило дисциплины источников выпало из deep_research"


def test_both_paths_share_the_exact_same_rule():
    """⚠️ Один текст на оба пути — копии не должны разъезжаться.

    Если завести две отдельные формулировки, они со временем разойдутся, и режимы станут
    по-разному относиться к вводным пользователя. Правило берётся из одного источника.
    """
    filled = DR_PROMPT.format(topic="тема", data="данные")
    # Ядро правила (первое предложение) присутствует дословно в обоих.
    core = _SOURCE_DISCIPLINE.split(".")[0].strip()
    assert core and core in _SYNTHESIS_PROMPT
    assert core in filled, "deep_research использует ДРУГУЮ формулировку правила"


def test_rule_names_people_explicitly():
    """Про конкретных людей — отдельная строка: это и был источник жалобы."""
    low = _SOURCE_DISCIPLINE.lower()
    assert "люд" in low, "правило не выделяет случай досье на людей — главный риск"


def test_rule_reaches_the_synthesis_call_in_web_search():
    """⚠️ Правило должно ДОЕХАТЬ до вызова, а не просто существовать константой.

    Мутация «собрать system_content без _SYNTHESIS_PROMPT» не роняет проверки текста
    выше. Поэтому смотрим тело _synthesize: system_content строится из _SYNTHESIS_PROMPT.
    """
    from service.domain.subagents.web_search import WebSearchAgent

    src = textwrap.dedent(inspect.getsource(WebSearchAgent._synthesize))
    tree = ast.parse(src)
    # где-то в теле system_content формируется с участием _SYNTHESIS_PROMPT
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "_SYNTHESIS_PROMPT" in names, (
        "система-промпт синтеза больше не использует _SYNTHESIS_PROMPT — правило не доедет"
    )
    assert re.search(r"system_content\s*=", src), "system_content не собирается в _synthesize"
