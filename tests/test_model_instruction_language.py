"""Русский язык инструкций без перевода протоколов и пользовательских источников."""

import importlib
import re
from types import SimpleNamespace

import pytest

from service.application.harness.proposal import contract_messages, contract_tool, repair_messages
from service.domain.capabilities.sources import TOOL_SOURCES
from service.domain.documents.authoring.protocol import (
    INTENT_TOOL,
    OUTLINE_TOOL,
    PATCH_TOOL,
    SECTION_TOOL,
)
from service.domain.documents.brief import normalize_brief
from service.domain.documents.skills.catalog import DOCUMENT_SKILL_CATALOG
from service.domain.documents.visual_audit import _AUDIT_TOOL, _messages
from service.domain.runners.chat.stream_state import _GROUNDING_REPAIR_NUDGE
from service.domain.tools.ide.command_validation import invalid_command
from service.domain.video_summary.protocol import TOOL, grouped_tool_for, tool_for


def _assert_russian(text):
    assert re.search(r"[А-Яа-яЁё]", text), f"Инструкция не на русском: {text!r}"
    # Идентификаторы, аббревиатуры и названия продуктов допустимы, английская проза — нет.
    assert not re.search(r"\b[A-Za-z]{2,}(?:[ ,]+[A-Za-z]{2,}){3,}\b", text), text


def _check_descriptions(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "description":
                _assert_russian(item)
            else:
                _check_descriptions(item)
    elif isinstance(value, list):
        for item in value:
            _check_descriptions(item)


@pytest.mark.parametrize("source", TOOL_SOURCES)
def test_builtin_tool_instructions_and_schema_descriptions_are_russian(source):
    # Только собственные инструменты: внешние MCP-схемы не переписываем.
    for spec in importlib.import_module(source).SPECS:
        _assert_russian(spec.tool.description)
        _check_descriptions(spec.tool.params_json_schema)


@pytest.mark.parametrize(
    "schema", [INTENT_TOOL, OUTLINE_TOOL, SECTION_TOOL, PATCH_TOOL, _AUDIT_TOOL, TOOL]
)
def test_internal_document_and_video_function_descriptions_are_russian(schema):
    _check_descriptions(schema)


@pytest.mark.parametrize("surface", ["ide", "pdf"])
def test_contract_admission_and_protocol_repair_instructions_are_russian(surface):
    admission = SimpleNamespace(surface=surface, actions=("read", "write"), goal="Original request")
    _check_descriptions(contract_tool(admission))
    messages = contract_messages(admission)
    _assert_russian(messages[0]["content"])
    assert messages[1]["content"] == "Запрос: Original request"
    _assert_russian(repair_messages(messages, "{}")[3]["content"])
    assert "criterion_id=verify_project" in messages[0]["content"]


@pytest.mark.parametrize("profile", tuple(DOCUMENT_SKILL_CATALOG.skills))
def test_document_editorial_instructions_are_russian_without_changing_output_locale(profile):
    _assert_russian(DOCUMENT_SKILL_CATALOG.semantic_instruction(profile))
    _assert_russian(DOCUMENT_SKILL_CATALOG.get(profile).system_instruction())
    assert normalize_brief("Подготовь документ на английском").locale == "en-US"


def test_visual_audit_and_execution_repair_instructions_are_russian():
    messages = _messages([(1, b"image")])
    _assert_russian(messages[0]["content"])
    _assert_russian(messages[1]["content"][0]["text"])
    assert messages[1]["content"][1]["text"] == "Страница 1."
    _assert_russian(_GROUNDING_REPAIR_NUDGE)
    _assert_russian(invalid_command().text)


def test_video_schema_translation_preserves_exact_source_text_and_protocol_identifiers():
    quote = "Do not translate this source quote."
    schema = tool_for(("cue_1",), (quote,))
    evidence = schema["function"]["parameters"]["properties"]["sections"]["items"]["properties"][
        "points"
    ]["items"]["properties"]["evidence"]["items"]["properties"]
    assert schema["function"]["name"] == "submit_video_notes"
    assert evidence["quote"]["enum"] == [quote]
    assert evidence["cue_ids"]["items"]["enum"] == ["cue_1"]
    _check_descriptions(schema)
    _check_descriptions(grouped_tool_for({"beginning": (("cue_1", quote),)}))
