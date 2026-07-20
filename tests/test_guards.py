"""Гарды сайдкара opendataloader: фильтр расширений и разметка ячеек.

Тесты живут против `core.py`, а не `app.py`, и это не стилистика: `app.py`
импортирует `opendataloader_pdf`, который тянет JVM. Проверять экранирование
ячейки, поднимая Java, никто не станет — значит проверять не будут вовсе.

Сознательно НЕ тестируются `soffice_convert` и `pdf_to_markdown`: это тонкие
обёртки над подпроцессом и чужой библиотекой, их отказы — отказы подпроцесса.
Замокать `subprocess.run` там значило бы протестировать мок.
"""

from __future__ import annotations

import pytest

from core import SUPPORTED_EXTENSIONS, _cell, extension_of


# --------------------------------------------------------------------------- #
# Экранирование ячеек: результат читает МОДЕЛЬ                                 #
# --------------------------------------------------------------------------- #
def test_pipe_is_escaped():
    """Труба в ячейке разорвала бы markdown-таблицу — модель увидела бы лишний столбец."""
    assert _cell("a|b") == r"a\|b"


def test_newline_is_flattened():
    """Перенос строки внутри ячейки ломает таблицу сильнее трубы: строка «уезжает»."""
    out = _cell("первая\nвторая")

    assert "\n" not in out
    assert out == "первая вторая"


def test_cell_that_is_itself_a_table_row_cannot_inject_structure():
    """Ячейка с содержимым «| x | y |» не должна становиться разметкой."""
    out = _cell("| x | y |")

    assert "\n" not in out
    assert out.count("|") == out.count(r"\|"), f"неэкранированная труба: {out!r}"


def test_none_becomes_empty_not_the_string_none():
    """`None` — обычное значение пустой ячейки. Строка «None» в таблице читалась бы
    моделью как данные."""
    assert _cell(None) == ""


def test_numbers_survive():
    assert _cell(0) == "0"
    assert _cell(3.5) == "3.5"


# --------------------------------------------------------------------------- #
# Фильтр расширений                                                            #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name",
    ["payload.exe", "script.sh", "archive.zip", "", "noext", ".hidden", "doc.pdf.exe"],
)
def test_unsupported_extensions_are_not_in_the_allowlist(name):
    """Разбор запускает подпроцессы, поэтому список РАЗРЕШЁННЫХ, а не запрещённых.

    `doc.pdf.exe` в списке специально: расширением считается ПОСЛЕДНЕЕ, и приём по
    «содержит .pdf» пропустил бы исполняемый файл.
    """
    assert extension_of(name) not in SUPPORTED_EXTENSIONS


@pytest.mark.parametrize("name", ["a.pdf", "b.docx", "c.xlsx", "d.ODS", "e.RtF"])
def test_supported_extensions_pass_case_insensitively(name):
    """Регистр приходит от пользователя: `.PDF` — тот же pdf."""
    assert extension_of(name) in SUPPORTED_EXTENSIONS
