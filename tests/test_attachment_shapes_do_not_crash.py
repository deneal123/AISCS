"""Форма вложения не роняет ход: словарь и модель читаются одинаково.

🔴 ЗАМЕРЕНО СКВОЗНЫМ РЕГРЕССОМ. Архив с вопросом «что за проект» — ответ:

    Сейчас не удалось получить ответ от модели. Проверьте API-ключ/доступ к провайдеру
    и повторите запрос.

Ключ был в порядке. В логах сайдкара:

    AttributeError: 'ModalityAttachment' object has no attribute 'get'
    auto_signals.py:95 in _attachment_shapes

Строка читала имя так: `getattr(item, "filename", None) or (item or {}).get("filename")`.
Вложение приезжает то СЛОВАРЁМ (тело `/run` список не типизирует), то МОДЕЛЬЮ — а в
модели поле зовётся `name`, не `filename`. На модели первый операнд давал `None`, второй
звал `.get` на pydantic-объекте, и падал ВЕСЬ ход.

⚠️ Цена ошибки удвоена текстом: человек читает «проверьте API-ключ» — совет, уводящий от
причины настолько далеко, насколько возможно, и заставляющий чинить то, что не сломано.
"""

from __future__ import annotations

from service.domain.routing.auto_signals import _attachment_shapes
from service.schemas.agents import ModalityAttachment


def test_a_model_attachment_does_not_crash():
    """🔴 ГЛАВНОЕ И ИМЕННО ЗАМЕРЕННЫЙ СЛУЧАЙ: вложение приехало моделью."""
    kinds, names = _attachment_shapes(
        [ModalityAttachment(kind="document", name="src.zip", content="карта")]
    )

    assert kinds == ["document"]
    assert names == ["src.zip"], "имя файла модели потеряно — решатель ослеп"


def test_a_dict_attachment_still_works():
    """🔴 ГРАНИЦА: словарная форма работала и обязана работать дальше."""
    kinds, names = _attachment_shapes([{"kind": "data", "filename": "sales.csv"}])

    assert kinds == ["data"]
    assert names == ["sales.csv"]


def test_both_field_names_are_read():
    """⚠️ Имя лежит то в `name`, то в `filename` — в этом коде живут обе формы, и читать
    надо обе. Одна прочитанная форма означает молча ослепший решатель."""
    _, by_name = _attachment_shapes([{"kind": "document", "name": "спека.pdf"}])
    _, by_filename = _attachment_shapes([{"kind": "document", "filename": "спека.pdf"}])

    assert by_name == by_filename == ["спека.pdf"]


def test_mixed_shapes_in_one_message():
    """🔴 ИМЕННО ТАК И БЫЛО В ЗАМЕРЕ: таблица словарём, документ моделью — в одном
    сообщении. Достаточно одного элемента чужой формы, чтобы ход упал целиком."""
    kinds, names = _attachment_shapes(
        [
            {"kind": "data", "filename": "sales.csv"},
            ModalityAttachment(kind="document", name="plan.txt"),
        ]
    )

    assert kinds == ["data", "document"]
    assert names == ["sales.csv", "plan.txt"]


def test_empty_and_broken_items_are_survivable():
    """⚠️ Пустые и незнакомые элементы не должны ронять ход: список приходит снаружи."""
    kinds, names = _attachment_shapes([None, {}, "строка", 42])

    assert kinds == [] and names == []


def test_no_attachments_is_quiet():
    """⚠️ Вложений нет — пусто, без исключений."""
    assert _attachment_shapes(None) == ([], [])
    assert _attachment_shapes([]) == ([], [])
