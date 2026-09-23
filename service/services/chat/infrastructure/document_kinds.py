"""Что считается ДОКУМЕНТОМ среди файлов сообщения — запасной путь без клиента.

Отдельный модуль, потому что у правила своя причина меняться (список расширений), а
`agent_context` и без того у потолка храповика: он самый крупный файл пакета.
"""

from __future__ import annotations

# Расширения, которые в промпт едут ТЕКСТОМ. Таблицы (csv/xlsx/json) сюда не входят: их
# содержимое замещается ссылкой для `analyze_data`, и в этом весь смысл отбрасывания.
_DOCUMENT_EXTENSIONS = (
    ".pdf",
    ".docx",
    ".doc",
    ".odt",
    ".rtf",
    ".txt",
    ".md",
    ".zip",
    ".py",
    ".js",
    ".ts",
    ".java",
    ".go",
    ".rs",
    ".sql",
    ".yaml",
    ".yml",
    ".toml",
)


def _document_among(files) -> bool:
    """Есть ли среди файлов ЭТОГО сообщения документ или код — по имени файла.

    ⚠️ Запасной путь, а не замена `attachments`: тот несёт модальность, вычисленную
    клиентом по содержимому (`.json` бывает и таблицей, и деревом настроек). Здесь же
    решает расширение — грубее, но не требует ничего от клиента.
    """
    for item in files or []:
        name = (item.get("name") or item.get("filename") or "") if isinstance(item, dict) else ""
        if str(name).lower().endswith(_DOCUMENT_EXTENSIONS):
            return True
    return False


# Модальности вложений, чей текст ложится в `file_context`. Клиент проставляет `kind`:
# data=таблица (csv/json/xlsx), image/audio=мультимодал, а document (pdf/docx/repo/…) и
# code — это и есть текст в промпте, который выбрасывать при наличии таблицы нельзя.
_DOCUMENT_KINDS = frozenset({"document", "code"})


def message_has_non_tabular_attachment(attachments) -> bool:
    """Есть ли в ЭТОМ сообщении НЕтабличное вложение (документ/репозиторий/код)?

    ⚠️ Оптимизация A1 убирает из промпта текст ТАБЛИЧНЫХ файлов (он дублируется ссылкой в
    `analyze_data`), но `file_context` — единый блоб: текст соседнего документа лежит там
    же. Живой инцидент: `.json` + `.zip` с просьбой отревьюить КОД — `.json` сделал
    таблицы непустыми, карту репозитория выбросило, агент ответил «вставьте код». Лишние
    токены дешевле ослепшего агента.

    ⚠️ По `attachments`, а НЕ по `user_file`: репозиторий идёт путём graphify и в
    `user_file` не персистится вовсе — запрос к БД его не увидел бы.
    """
    for att in attachments or []:
        kind = att.get("kind") if isinstance(att, dict) else getattr(att, "kind", None)
        if str(kind or "document") in _DOCUMENT_KINDS:
            return True
    return False
