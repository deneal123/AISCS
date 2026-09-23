"""Backend распознаёт документ/репозиторий рядом с таблицей.

🔴 ЖИВОЙ ИНЦИДЕНТ. Пользователь приложил .json-датасет + .zip-репозиторий и попросил
ревью КОДА. Оптимизация A1 в сайдкаре выбрасывает file_context при непустых
tabular_files; .json сделал их непустыми, и карту репозитория выбросило — агент ответил
«вставьте код». Backend по вложениям сообщения сообщает сайдкару, что рядом с таблицей
есть нетабличный файл, чтобы file_context не выбрасывался.

⚠️ Сигнал по `attachments`, а НЕ по user_file: репозиторий (.zip) идёт путём graphify и
в user_file не персистится — БД его не увидела бы. Клиентский `kind` — единственный
источник, где repo/документ виден рядом с таблицей.
"""

from __future__ import annotations

from service.services.chat.infrastructure.agent_context import (
    message_has_non_tabular_attachment as has_doc,
)


def test_repo_next_to_dataset_is_detected():
    """⚠️ ГЛАВНОЕ. .zip-репо (kind=document) рядом с .json (kind=data) → есть документ."""
    attachments = [
        {"kind": "data", "name": "dataset.json"},
        {"kind": "document", "name": "consultant_driver.zip"},
    ]
    assert has_doc(attachments) is True


def test_code_attachment_counts_as_document():
    """Код (kind=code) — тоже текст в file_context, не таблица."""
    assert has_doc([{"kind": "code", "name": "main.py"}]) is True


def test_only_tabular_data_is_false():
    """Только табличные (kind=data) → нетабличных нет, поведение A1 прежнее."""
    assert has_doc([{"kind": "data", "name": "a.json"}, {"kind": "data", "name": "b.csv"}]) is False


def test_media_only_is_false():
    """Картинка/аудио — мультимодал, их текста в file_context нет → не документ."""
    assert has_doc([{"kind": "image", "name": "photo.png"}]) is False


def test_missing_kind_defaults_to_document():
    """Нет kind → считаем документом (безопаснее сохранить file_context, чем потерять)."""
    assert has_doc([{"name": "unknown.bin"}]) is True


def test_empty_attachments_is_false():
    assert has_doc([]) is False
    assert has_doc(None) is False


def test_wired_into_worker():
    """⚠️ Сигнал ПОДКЛЮЧЁН к потоку и доезжает до execute."""
    import inspect

    # ⚠️ СБОР ПЕРЕЕХАЛ в `chat_worker/turn_context.py` (вынос из разросшейся функции), а
    # ПЕРЕДАЧА движку осталась в воркере. Стережём оба звена: правило живёт в цепочке, и
    # разрыв в любом из них так же нем, как раньше.
    from service.services.chat.infrastructure.chat_worker import turn_context as tc

    collected = inspect.getsource(tc.collect_engine_inputs)
    from service.services.chat.infrastructure.chat_worker import run_execution

    passed = inspect.getsource(run_execution._execute_agent)
    assert "collect_message_extras" in collected, (
        "сигнал о документе рядом с таблицей не собирается"
    )
    assert "has_non_tabular_attachment=prepared.has_non_tabular_attachment" in passed, (
        "флаг не передаётся в execute — сайдкар не узнает про документ"
    )
