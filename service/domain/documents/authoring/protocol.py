"""Provider-neutral function schemas and response parsing for document authoring."""

from __future__ import annotations

import json
from collections.abc import Iterable
from copy import deepcopy
from typing import Any

INTENT_FUNCTION = "submit_document_intent"
OUTLINE_FUNCTION = "submit_document_outline"
SECTION_FUNCTION = "submit_document_section"
PATCH_FUNCTION = "submit_document_patch"


def _field(field_type: str, description: str, **extra: Any) -> dict[str, Any]:
    return {"type": field_type, "description": description, **extra}


INTENT_TOOL = {
    "type": "function",
    "function": {
        "name": INTENT_FUNCTION,
        "description": "Привести запрос документа к поддерживаемому контракту подготовки.",
        "parameters": {
            "type": "object",
            "description": "Замысел документа в пределах поддерживаемых возможностей.",
            "properties": {
                "kind": _field(
                    "string",
                    "Поддерживаемый вид документа.",
                    enum=["generic", "article", "presentation", "legal", "report", "unsupported"],
                ),
                "profile_id": _field(
                    "string",
                    "Точный идентификатор совместимого профиля.",
                    enum=[
                        "generic_document",
                        "generic_article",
                        "ieee_journal",
                        "aaai_conference",
                        "beamer_16_9",
                        "legal_ru",
                        "generic_report",
                    ],
                ),
                "locale": _field("string", "Языковая локаль документа.", enum=["ru-RU", "en-US"]),
                "mode": _field(
                    "string",
                    "Режим жизненного цикла документа.",
                    enum=["draft", "submission", "camera_ready"],
                ),
                "title": _field("string", "Запрошенное название документа."),
                "audience": _field("string", "Предполагаемые читатели."),
                "length_class": _field(
                    "string", "Категория объёма.", enum=["short", "standard", "long"]
                ),
                "required_sections": _field(
                    "array",
                    "Названия обязательных разделов.",
                    items=_field("string", "Название одного раздела."),
                ),
                "citation_policy": _field(
                    "string", "Требование к источникам.", enum=["none", "optional", "required"]
                ),
                "presentation_density": _field(
                    "string", "Плотность содержания слайда.", enum=["sparse", "balanced", "dense"]
                ),
                "legal_fields": _field(
                    "array",
                    "Известные или незаполненные юридические реквизиты.",
                    items={
                        "type": "object",
                        "description": "Один юридический реквизит.",
                        "properties": {
                            "name": _field("string", "Стабильное имя поля."),
                            "value": _field("string", "Известное значение или пустая строка."),
                            "required": _field(
                                "boolean", "Обязательно ли значение для финальной публикации."
                            ),
                        },
                        "required": ["name", "value", "required"],
                        "additionalProperties": False,
                    },
                ),
                "user_requirements": _field(
                    "array",
                    "Безопасные пользовательские требования к оформлению или содержанию.",
                    items=_field("string", "Одно требование."),
                ),
            },
            "required": [
                "kind",
                "profile_id",
                "locale",
                "mode",
                "title",
                "audience",
                "length_class",
                "required_sections",
                "citation_policy",
                "presentation_density",
                "legal_fields",
                "user_requirements",
            ],
            "additionalProperties": False,
        },
    },
}

BLOCK_SCHEMA = {
    "type": "object",
    "description": "Один семантический блок документа; неиспользуемые поля пусты.",
    "properties": {
        "block_id": _field("string", "Стабильный идентификатор в нижнем регистре."),
        "kind": _field(
            "string",
            "Тип семантического блока.",
            enum=[
                "section",
                "paragraph",
                "list",
                "table",
                "figure",
                "equation",
                "callout",
                "slide",
                "signature",
                "citation",
            ],
        ),
        "title": _field("string", "Заголовок, подпись или название слайда."),
        "text": _field("string", "Обычный текст без LaTeX."),
        "items": _field(
            "array", "Элементы списка или подписи.", items=_field("string", "Текстовый элемент.")
        ),
        "columns": _field(
            "array", "Заголовки столбцов таблицы.", items=_field("string", "Заголовок столбца.")
        ),
        "rows": _field(
            "array",
            "Строки таблицы.",
            items=_field("array", "Строка таблицы.", items=_field("string", "Ячейка таблицы.")),
        ),
        "source_id": _field(
            "integer",
            "Идентификатор зарегистрированного источника для цитаты или слайда; иначе ноль.",
            minimum=0,
        ),
        "asset_path": _field("string", "Относительный путь иллюстрации или пустая строка."),
        "level": _field("integer", "Уровень заголовка от одного до трёх.", minimum=1, maximum=3),
    },
    "required": [
        "block_id",
        "kind",
        "title",
        "text",
        "items",
        "columns",
        "rows",
        "source_id",
        "asset_path",
        "level",
    ],
    "additionalProperties": False,
}

AUTHOR_BLOCK_SCHEMA = {
    **BLOCK_SCHEMA,
    "properties": {
        key: value for key, value in BLOCK_SCHEMA["properties"].items() if key != "block_id"
    },
    "required": [key for key in BLOCK_SCHEMA["required"] if key != "block_id"],
}

OUTLINE_TOOL = {
    "type": "function",
    "function": {
        "name": OUTLINE_FUNCTION,
        "description": "Вернуть семантический план в заданных пределах, без пояснений и LaTeX.",
        "parameters": {
            "type": "object",
            "description": "План документа; стабильные идентификаторы назначает доверенный код.",
            "properties": {
                "title": _field("string", "Название документа."),
                "sections": _field(
                    "array",
                    "Разделы в порядке подготовки.",
                    minItems=1,
                    maxItems=16,
                    items={
                        "type": "object",
                        "description": "План одного раздела в заданных пределах.",
                        "properties": {
                            "title": _field("string", "Название раздела или группы слайдов."),
                            "purpose": _field("string", "Факты и назначение этого раздела."),
                            "block_kinds": _field(
                                "array",
                                "Типы семантических блоков, необходимые в этом разделе.",
                                minItems=1,
                                maxItems=12,
                                items=BLOCK_SCHEMA["properties"]["kind"],
                            ),
                            "source_ids": _field(
                                "array",
                                "Только идентификаторы предоставленных материалов или источников.",
                                maxItems=64,
                                items=_field("string", "Непрозрачный идентификатор источника."),
                            ),
                        },
                        "required": ["title", "purpose", "block_kinds", "source_ids"],
                        "additionalProperties": False,
                    },
                ),
            },
            "required": ["title", "sections"],
            "additionalProperties": False,
        },
    },
}

SECTION_TOOL = {
    "type": "function",
    "function": {
        "name": SECTION_FUNCTION,
        "description": "Подготовить ровно один запланированный семантический раздел без LaTeX.",
        "parameters": {
            "type": "object",
            "description": "Один подготовленный раздел принятого плана.",
            "properties": {
                "blocks": _field(
                    "array",
                    "Семантические блоки этого раздела по порядку.",
                    minItems=1,
                    maxItems=24,
                    items=AUTHOR_BLOCK_SCHEMA,
                ),
            },
            "required": ["blocks"],
            "additionalProperties": False,
        },
    },
}


def compile_section_tool(
    allowed_source_ids: Iterable[int],
    allowed_block_kinds: Iterable[str],
) -> dict[str, Any]:
    """Bind citation arguments to the exact private evidence registry for this run."""

    compiled = deepcopy(SECTION_TOOL)
    block_properties = compiled["function"]["parameters"]["properties"]["blocks"]["items"][
        "properties"
    ]
    source_schema = block_properties["source_id"]
    source_schema["enum"] = [0, *sorted({int(item) for item in allowed_source_ids if item > 0})]
    block_properties["kind"]["enum"] = sorted(
        {str(item) for item in allowed_block_kinds if str(item) and str(item) != "section"}
    )
    return compiled


PATCH_TOOL = {
    "type": "function",
    "function": {
        "name": PATCH_FUNCTION,
        "description": "Заменить только указанные блоки существующего семантического черновика.",
        "parameters": {
            "type": "object",
            "description": "Правка семантических блоков в заданных пределах.",
            "properties": {
                "base_version": _field("integer", "Точная текущая версия черновика.", minimum=1),
                "replacements": _field(
                    "array", "Блоки замены с существующими идентификаторами.", items=BLOCK_SCHEMA
                ),
            },
            "required": ["base_version", "replacements"],
            "additionalProperties": False,
        },
    },
}


def response_arguments(response: Any, function_name: str) -> dict[str, Any] | None:
    choices = getattr(response, "choices", None) or []
    if len(choices) != 1:
        return None
    message = getattr(choices[0], "message", None)
    calls = getattr(message, "tool_calls", None) or []
    function: Any = None
    if len(calls) == 1:
        function = getattr(calls[0], "function", None)
        if function is None and isinstance(calls[0], dict):
            function = calls[0].get("function")
    elif not calls:
        # GigaChat's native response dialect is ``function_call``.  The
        # provider adapter normally canonicalizes it, but SDK envelopes with
        # provider-specific optional fields may remain typed in the native
        # shape.  Reading that exact field here is not a text/JSON fallback:
        # name and object arguments are validated identically below.
        function = getattr(message, "function_call", None)
        if function is None and isinstance(message, dict):
            function = message.get("function_call")
    else:
        return None
    if isinstance(function, dict):
        name = function.get("name")
        raw = function.get("arguments")
    else:
        name = getattr(function, "name", "")
        raw = getattr(function, "arguments", None)
    if str(name or "") != function_name:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or ""))
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


__all__ = [
    "INTENT_FUNCTION",
    "INTENT_TOOL",
    "OUTLINE_FUNCTION",
    "OUTLINE_TOOL",
    "PATCH_FUNCTION",
    "PATCH_TOOL",
    "SECTION_FUNCTION",
    "SECTION_TOOL",
    "compile_section_tool",
    "response_arguments",
]
