"""Общий nullable не должен отвергать допустимые CommandSpec null или расширять enum."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from local_llm.service.domain.protocol.contracts import ProtocolFailure
from local_llm.service.domain.protocol.schema import native_schema


def test_nullable_changes_type_without_mutating_enum_or_callers_schema():
    original = {"type": "string", "nullable": True, "enum": ["allowed"]}
    before = deepcopy(original)
    result = native_schema(original)
    assert result == {"type": ["string", "null"], "enum": ["allowed"]}
    assert original == before
    assert not Draft202012Validator(result).is_valid(None)


def test_nullable_string_allows_null_without_relaxing_pattern():
    schema = native_schema({"type": "string", "nullable": True, "pattern": "^[a-z]+$"})
    validator = Draft202012Validator(schema)
    assert validator.is_valid(None) and validator.is_valid("script")
    assert not validator.is_valid(12) and not validator.is_valid("/script")


def test_named_properties_and_literal_values_are_not_schema_keywords():
    literal = {"type": "string", "nullable": True}
    source = {
        "type": "object",
        "properties": {"nullable": {"type": "integer", "nullable": True}},
        "default": literal,
        "enum": [literal],
        "examples": [literal],
    }
    result = native_schema(source)
    assert result["properties"]["nullable"] == {"type": ["integer", "null"]}
    for key in ("default", "enum", "examples"):
        assert result[key] == source[key]


def test_arrays_definitions_and_composition_translate_only_schema_children():
    child = {"type": "integer", "nullable": True}
    result = native_schema(
        {
            "type": "object",
            "$defs": {"item": child},
            "properties": {"values": {"type": "array", "items": child}},
            "anyOf": [{"additionalProperties": child}],
        }
    )
    expected = {"type": ["integer", "null"]}
    assert result["$defs"]["item"] == expected
    assert result["properties"]["values"]["items"] == expected
    assert result["anyOf"][0]["additionalProperties"] == expected


def test_nullable_without_explicit_type_does_not_invent_a_type():
    assert native_schema({"nullable": True, "enum": ["only"]}) == {"enum": ["only"]}
    assert native_schema({"type": "string", "nullable": False}) == {"type": "string"}


@pytest.mark.parametrize("value", ["true", 1, None])
def test_invalid_nullable_is_not_silently_interpreted_as_truthy(value):
    with pytest.raises(ProtocolFailure, match="tool_schema_invalid"):
        native_schema({"type": "string", "nullable": value})
