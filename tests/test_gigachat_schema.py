"""Offline GigaChat function-schema compatibility gate."""

from __future__ import annotations

import pytest

from service.domain.capabilities.tool_registry import tool_specs
from service.domain.client.providers.gigachat_schema import (
    GigaChatToolSchemaError,
    prepare_gigachat_functions,
)
from service.domain.runners.support import _tools_to_openai


def _function(parameters: dict) -> dict:
    return {"name": "external_lookup", "description": "Lookup", "parameters": parameters}


def test_all_static_tools_are_gigachat_compatible() -> None:
    functions = [
        item["function"] for item in _tools_to_openai([s.tool for s in tool_specs().values()])
    ]

    prepared = prepare_gigachat_functions(functions, fill_missing_descriptions=False)

    assert [item["name"] for item in prepared] == [item["name"] for item in functions]
    issue = next(item for item in prepared if item["name"] == "ws_issue_update")
    assert issue["parameters"]["properties"]["status"]["description"] == "Новый статус issue."


def test_missing_dynamic_descriptions_are_filled_without_mutating_source() -> None:
    raw = _function(
        {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
            "required": ["filters"],
        }
    )

    prepared = prepare_gigachat_functions([raw])[0]

    prop = prepared["parameters"]["properties"]["filters"]
    assert prop["description"] == "External tool parameter."
    assert prop["items"]["description"] == "External tool parameter."
    assert "description" not in raw["parameters"]["properties"]["filters"]


def test_static_schema_missing_description_is_rejected() -> None:
    raw = _function(
        {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["open", "closed"]}},
        }
    )

    with pytest.raises(GigaChatToolSchemaError, match="tool_schema"):
        prepare_gigachat_functions([raw], fill_missing_descriptions=False)


def test_nullable_is_preserved_but_must_be_boolean() -> None:
    raw = _function(
        {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Query", "nullable": True}},
        }
    )

    prepared = prepare_gigachat_functions([raw], fill_missing_descriptions=False)
    assert prepared[0]["parameters"]["properties"]["query"]["nullable"] is True

    raw["parameters"]["properties"]["query"]["nullable"] = "yes"
    with pytest.raises(GigaChatToolSchemaError, match="tool_schema"):
        prepare_gigachat_functions([raw], fill_missing_descriptions=False)


@pytest.mark.parametrize(
    "parameters",
    [
        {"type": "object", "properties": {}, "oneOf": []},
        {"type": "object", "properties": {}, "additionalProperties": {"type": "string"}},
        {"type": ["object", "null"], "properties": {}},
        {"type": "array", "items": [{"type": "string"}]},
        {"type": "object", "properties": {}, "required": ["missing"]},
    ],
)
def test_unsupported_schema_is_rejected_without_echoing_it(parameters: dict) -> None:
    with pytest.raises(GigaChatToolSchemaError) as caught:
        prepare_gigachat_functions([_function(parameters)])

    assert str(caught.value) == "tool_schema"
    assert "oneOf" not in str(caught.value)


def test_one_invalid_function_rejects_the_whole_batch() -> None:
    valid = _function({"type": "object", "properties": {}})
    invalid = _function({"type": "object", "properties": {}, "$ref": "private"})

    with pytest.raises(GigaChatToolSchemaError) as caught:
        prepare_gigachat_functions([valid, invalid])

    assert caught.value.invalid_count == 1
