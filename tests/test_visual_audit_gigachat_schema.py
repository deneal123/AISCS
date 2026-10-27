"""Internal metered stage functions need the same strict corpus as native tools."""

import pytest

from service.domain.client.protocol.capabilities import GIGACHAT_TOOL_CAPABILITIES
from service.domain.client.protocol.compiler import compile_toolset
from service.domain.documents.authoring.protocol import (
    INTENT_TOOL,
    OUTLINE_TOOL,
    PATCH_TOOL,
    SECTION_TOOL,
)
from service.domain.documents.visual_audit import _AUDIT_FUNCTION, _AUDIT_TOOL
from service.domain.video_summary.protocol import TOOL as VIDEO_NOTES_TOOL


def _closed_objects(value):
    if isinstance(value, list):
        return [_closed_objects(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _closed_objects(item) for key, item in value.items()}
    if result.get("type") == "object":
        result.setdefault("additionalProperties", False)
    return result


def test_visual_audit_schema_compiles_without_dynamic_description_fallback():
    compiled = compile_toolset(
        [_AUDIT_TOOL],
        provider="gigachat",
        capabilities=GIGACHAT_TOOL_CAPABILITIES,
        tool_choice={"type": "function", "function": {"name": _AUDIT_FUNCTION}},
    )
    assert len(compiled.functions) == 1
    assert compiled.functions[0]["parameters"] == _AUDIT_TOOL["function"]["parameters"]
    assert compiled.max_calls_per_round == 1


@pytest.mark.parametrize(
    "tool", [INTENT_TOOL, OUTLINE_TOOL, SECTION_TOOL, PATCH_TOOL, VIDEO_NOTES_TOOL]
)
def test_document_and_video_stage_schemas_compile_strictly(tool):
    name = tool["function"]["name"]
    compiled = compile_toolset(
        [tool],
        provider="gigachat",
        capabilities=GIGACHAT_TOOL_CAPABILITIES,
        tool_choice={"type": "function", "function": {"name": name}},
    )
    assert compiled.functions[0]["parameters"] == _closed_objects(tool["function"]["parameters"])
    assert compiled.max_calls_per_round == 1
