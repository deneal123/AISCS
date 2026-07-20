"""Логика сайдкара opendataloader, не требующая тяжёлых зависимостей.

Шов между транспортом и логикой здесь окупается конкретнее, чем у соседей:
`app.py` импортирует `opendataloader_pdf` на уровне модуля, а тот тянет JVM.
Без этого файла проверить фильтр расширений и экранирование ячеек можно было бы
только подняв Java — то есть практически никогда.

`MAX_SHEET_ROWS` тоже здесь: обрезка листа читается из окружения, а тест на неё
не должен зависеть от LibreOffice.
"""

import os
from pathlib import Path

# Побочный эффект импорта: подкладывает дефолты из settings.toml ПОД окружение.
# Стоит здесь, а не в app.py, потому что именно этот модуль читает переменные на
# уровне модуля — значит он и должен гарантировать, что дефолты уже применены.
import settings  # noqa: F401

MAX_SHEET_ROWS = int(os.environ.get("ODL_MAX_SHEET_ROWS", "2000"))

SPREADSHEET_EXTENSIONS = (".xlsx", ".xls", ".ods")
# Свёрстанные документы — через LibreOffice → PDF → opendataloader. Текстовые форматы
# (txt/md/csv/json/код) сюда НЕ входят: бэкенд читает их сам.
DOCUMENT_EXTENSIONS = (
    ".docx",
    ".doc",
    ".odt",
    ".rtf",
    ".pptx",
    ".ppt",
    ".odp",
    ".html",
    ".htm",
)
SUPPORTED_EXTENSIONS = (".pdf", *DOCUMENT_EXTENSIONS, *SPREADSHEET_EXTENSIONS)


def extension_of(filename):
    return Path(str(filename or "")).suffix.lower()


def _cell(value):
    if value is None:
        return ""
    # Трубы сломали бы разметку markdown-таблицы.
    return str(value).replace("|", "\\|").replace("\n", " ").strip()
