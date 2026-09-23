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
        "description": "Normalize one document request into the supported authoring contract.",
        "parameters": {
            "type": "object",
            "description": "Bounded document intent.",
            "properties": {
                "kind": _field(
                    "string",
                    "Supported document kind.",
                    enum=["generic", "article", "presentation", "legal", "report", "unsupported"],
                ),
                "profile_id": _field(
                    "string",
                    "Exact compatible profile identifier.",
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
                "locale": _field("string", "Document language locale.", enum=["ru-RU", "en-US"]),
                "mode": _field(
                    "string",
                    "Document lifecycle mode.",
                    enum=["draft", "submission", "camera_ready"],
                ),
                "title": _field("string", "Requested document title."),
                "audience": _field("string", "Intended readers."),
                "length_class": _field(
                    "string", "Bounded length class.", enum=["short", "standard", "long"]
                ),
                "required_sections": _field(
                    "array",
                    "Required section labels.",
                    items=_field("string", "One section label."),
                ),
                "citation_policy": _field(
                    "string", "Evidence requirement.", enum=["none", "optional", "required"]
                ),
                "presentation_density": _field(
                    "string", "Amount of content per slide.", enum=["sparse", "balanced", "dense"]
                ),
                "legal_fields": _field(
                    "array",
                    "Known or unresolved legal fields.",
                    items={
                        "type": "object",
                        "description": "One legal field.",
                        "properties": {
                            "name": _field("string", "Stable field name."),
                            "value": _field("string", "Known value or empty string."),
                            "required": _field(
                                "boolean", "Whether final publication requires a value."
                            ),
                        },
                        "required": ["name", "value", "required"],
                        "additionalProperties": False,
                    },
                ),
                "user_requirements": _field(
                    "array",
                    "Safe user-authored layout or content requirements.",
                    items=_field("string", "One requirement."),
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
    "description": "One semantic document block; unused fields are empty.",
    "properties": {
        "block_id": _field("string", "Stable lowercase identifier."),
        "kind": _field(
            "string",
            "Semantic block kind.",
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
        "title": _field("string", "Heading, caption, or slide title."),
        "text": _field("string", "Plain text content without LaTeX."),
        "items": _field(
            "array", "List or signature values.", items=_field("string", "Plain text item.")
        ),
        "columns": _field(
            "array", "Table column headings.", items=_field("string", "Column heading.")
        ),
        "rows": _field(
            "array",
            "Table rows.",
            items=_field("array", "One table row.", items=_field("string", "Table cell.")),
        ),
        "source_id": _field(
            "integer",
            "Registered evidence ID for citation and slide blocks, or zero when unused.",
            minimum=0,
        ),
        "asset_path": _field("string", "Relative figures path, or empty string."),
        "level": _field("integer", "Heading level from one to three.", minimum=1, maximum=3),
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
        "description": "Return a bounded semantic outline without prose or LaTeX.",
        "parameters": {
            "type": "object",
            "description": "Document outline whose stable IDs are assigned by trusted code.",
            "properties": {
                "title": _field("string", "Document title."),
                "sections": _field(
                    "array",
                    "Ordered authoring sections.",
                    minItems=1,
                    maxItems=16,
                    items={
                        "type": "object",
                        "description": "One bounded section plan.",
                        "properties": {
                            "title": _field("string", "Visible section or slide-group title."),
                            "purpose": _field("string", "Facts and purpose this section covers."),
                            "block_kinds": _field(
                                "array",
                                "Semantic block kinds required in this section.",
                                minItems=1,
                                maxItems=12,
                                items=BLOCK_SCHEMA["properties"]["kind"],
                            ),
                            "source_ids": _field(
                                "array",
                                "Only supplied material or research source identifiers.",
                                maxItems=64,
                                items=_field("string", "Opaque source identifier."),
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
        "description": "Author exactly one planned semantic section without LaTeX.",
        "parameters": {
            "type": "object",
            "description": "One completed section from the accepted outline.",
            "properties": {
                "blocks": _field(
                    "array",
                    "Ordered semantic blocks for this section.",
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
        "description": "Replace only named blocks in the existing semantic draft.",
        "parameters": {
            "type": "object",
            "description": "Bounded semantic block patch.",
            "properties": {
                "base_version": _field("integer", "Exact current draft version.", minimum=1),
                "replacements": _field(
                    "array", "Replacement blocks with existing IDs.", items=BLOCK_SCHEMA
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
