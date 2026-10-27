"""Image-plus-tool calls require both capabilities in the same admitted model."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.client.calls.chat import _chat_candidate
from service.domain.client.calls.stream_candidate import select_stream_candidate
from service.domain.client.models.catalog import CapabilityEvidenceSource, ProviderModelRecord
from service.domain.client.models.requirements import ModelRequirement
from tests.test_s33_provider_generation import _admission

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "submit_audit",
            "description": "Submit a bounded audit result.",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def record(name, capabilities):
    return ProviderModelRecord(
        model_id=name,
        capabilities=frozenset(capabilities),
        evidence_source=CapabilityEvidenceSource.LOCAL_PROFILE,
    )


async def candidate(mode, admission, requirement):
    kwargs = dict(
        admission=admission,
        requirement=requirement,
        tools=_TOOLS,
        tool_choice={"type": "function", "function": {"name": "submit_audit"}},
    )
    if mode == "chat":
        _client, model, compiled, failure, _status = await _chat_candidate(
            "openai", None, prefer_model="tool-only", **kwargs
        )
    else:
        _client, model, compiled, failure = await select_stream_candidate(
            "openai",
            None,
            requested_model="tool-only",
            qualify=AsyncMock(side_effect=AssertionError("global discovery forbidden")),
            **kwargs,
        )
    return SimpleNamespace(model=model, compiled=compiled, failure=failure)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "stream"])
async def test_image_tools_cannot_admit_a_text_only_model(mode):
    admission = _admission(object(), record("tool-only", {"chat", "tools"}))
    result = await candidate(mode, admission, ModelRequirement(tools=True, vision=True))
    assert result.model is None
    assert result.compiled is None
    assert result.failure is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "stream"])
async def test_combined_requirements_do_not_reuse_text_only_admission_cache(mode):
    admission = _admission(
        object(),
        record("tool-only", {"chat", "tools"}),
        record("vision-tool", {"chat", "tools", "vision"}),
    )
    text = await candidate(mode, admission, ModelRequirement(tools=True))
    vision = await candidate(mode, admission, ModelRequirement(tools=True, vision=True))
    assert text.model == "tool-only"
    assert vision.model == "vision-tool"
    assert vision.compiled is not None
    assert vision.failure is None
    assert (await candidate(mode, admission, ModelRequirement(tools=True))).model == text.model
