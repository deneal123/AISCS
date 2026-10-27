"""Чтение ответа chat/completions — в одном месте.

⚠️ ЗАЧЕМ. Один и тот же разбор
``getattr(getattr(resp.choices[0], "message", None), "content", None)`` был скопирован по
домену ОДИННАДЦАТЬ раз: в компрессоре контекста, декомпозиции, планировщике, оценке
сложности, аварийном пути SDK, субагентах. Каждая копия чуть отличалась — где-то дефолт
``""``, где-то ``None``, где-то со ``.strip()``, где-то без, — и все они молча возвращали
пустую строку на ответе неожиданной формы.

Модуль намеренно БЕЗ ЗАВИСИМОСТЕЙ: его импортируют и `domain/pipeline`, и
`domain/runners`, и `domain/subagents`. Любая доменная зависимость здесь замкнула бы
кольцо, как это уже случилось с нарезкой чанков и накопителем usage.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def first_message_content(response: Any) -> str:
    """Текст первого варианта ответа. Пустая строка — если его нет.

    ⚠️ Пустая строка НЕ означает «модель промолчала»: так же выглядит ответ странной
    формы (нет `choices`, нет `message`). Вызывающему, которому это различие важно,
    надо смотреть на `finish_reason` и usage, а не на длину строки — здесь их не видно
    по устройству.

    Поддерживаются SDK-объекты и декодированные mapping-ответы. Неизвестное
    содержимое не преобразуется в repr: там могут оказаться приватные поля.
    """
    choices = _field(response, "choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        return ""
    message = _field(choices[0], "message")
    content = _field(message, "content")
    return content if isinstance(content, str) else ""
