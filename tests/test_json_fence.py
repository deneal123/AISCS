"""Снятие markdown-ограждения с JSON — один разбор вместо четырёх.

⚠️ Обходов было ЧЕТЫРЕ, и все вели себя по-разному на неровном ответе: `strip("`")` в
декомпозиции снимал любое число кавычек с обоих концов; регулярка роутера стояла с
`MULTILINE` и трогала ограждение в СЕРЕДИНЕ текста; `split("\n", 1)[-1]` в pptx и
нативном ресёрче терял первую строку, если ограждения нет, но текст на него похож.

Разница вылезла бы не всегда, а на первом же нестандартном ответе — и в каждом месте
по-своему.
"""

from __future__ import annotations

import pytest

from service.domain.json_fence import strip_json_fence


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ("```\n[1, 2]\n```", "[1, 2]"),
        ("~~~json\n{}\n~~~", "{}"),
        ('  ```json\n{"a": 1}\n```  ', '{"a": 1}'),
        ('{"a": 1}', '{"a": 1}'),
        ("[1, 2]", "[1, 2]"),
        ("", ""),
    ],
)
def test_strips_only_a_matching_fence(raw, expected):
    assert strip_json_fence(raw) == expected


def test_keeps_backticks_that_are_part_of_the_payload():
    """⚠️ Тройка ВНУТРИ значения — содержимое, а не ограждение.

    Прежний `raw.strip("`")` съедал её вместе с настоящим ограждением и ломал JSON:
    модель показывает пример кода в поле, а разбор падает.
    """
    raw = '```json\n{"code": "x = ```"}\n```'

    assert strip_json_fence(raw) == '{"code": "x = ```"}'


def test_lone_fence_is_not_stripped():
    """Одинокая открывающая тройка без закрывающей — это содержимое.

    Снять её значило бы отрезать первую строку у ответа, в котором ограждения нет.
    """
    raw = "```json\nне закрыто"

    assert strip_json_fence(raw) == raw


def test_every_caller_uses_the_shared_stripper():
    """⚠️ Проверка МЕСТА ВЫЗОВА: свои обходы не должны вернуться.

    Сама функция может быть сколь угодно правильной — четыре модуля до этого прекрасно
    обходились без неё.
    """
    import inspect

    from service.domain.pipeline import decomposition
    from service.domain.subagents.research import planner as research_planner
    from service.domain.tools import pptx, router

    for module in (decomposition, router, pptx, research_planner):
        source = inspect.getsource(module)
        assert "strip_json_fence(" in source, f"{module.__name__} не пользуется общим разбором"
        assert 'rsplit("```"' not in source, f"{module.__name__}: вернулся свой обход"
        assert 'strip("`")' not in source, f"{module.__name__}: вернулся свой обход"
