"""Структурный инструмент остаётся предложением выбранной версии и области."""

import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from service.application.admission.document_tools import apply_document_tool_consent
from service.domain.client.protocol import (
    GIGACHAT_TOOL_CAPABILITIES,
    OPENAI_TOOL_CAPABILITIES,
    compile_toolset,
)
from service.domain.documents.semantic.draft import DraftBlock
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.support import _tools_to_openai
from service.domain.subagents.general import GeneralAgent
from service.domain.tools.documents import structure


def block(identity, text="Без изменений"):
    return {**DraftBlock(identity, "slide", text=text).payload(), "source_id": 0}


def target():
    return {
        "path": "documents/slides",
        "project_id": "owned",
        "expected_revision": "r1",
        "draft_digest": "a" * 64,
        "tools_auto_approved": True,
        "patch_version": 2,
        "block_ids": ["intro"],
        "content": json.dumps(
            {"title": "Котики", "version": 3, "blocks": [block("intro"), block("keep")]}
        ),
    }


def patch():
    return {
        "base_version": 3,
        "replacements": [block("intro", "Мир котиков")],
        "deletions": [],
        "moves": [],
        "insertions": [
            {"after_id": "intro", "block": block("new_cat_2", "Повадки")},
            {"after_id": "new_cat_2", "block": block("new_cat_3", "Забота")},
        ],
    }


@pytest.mark.asyncio
async def test_three_slides_are_one_review_without_source_write_or_fake_evidence(monkeypatch):
    document, arguments = target(), patch()
    saved = deepcopy((document, arguments))
    remote = AsyncMock(return_value={"proposal_id": "b" * 32})
    monkeypatch.setattr(structure, "call", remote)
    with use_run_execution(
        PrivateRunResources(workspace_ref={"document_context": document})
    ) as execution:
        assert apply_document_tool_consent(execution)
        outcome = await structure.propose_structure(None, json.dumps(arguments))
        assert outcome.succeeded and json.loads(outcome.text)["status"] == "awaiting_review"
        assert not execution.workspace.ide_writes and execution.task_state is None
        assert execution.policy.values["document_proposal"] == "b" * 32
    remote.assert_awaited_once()
    assert remote.call_args.args[1] == "documents/proposals"
    stored = remote.call_args.args[2]["proposal"]
    assert stored["patch_version"] == 2 and stored["base_version"] == 3
    assert stored["selected_block_ids"] == ["intro"]
    assert [item["block"]["block_id"] for item in stored["insertions"]] == [
        "new_cat_2",
        "new_cat_3",
    ]
    assert (document, arguments) == saved


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,reason",
    [
        ("version", "stale_base_version"),
        ("selection", "outside_selection"),
        ("id", "new_block_id_required"),
        ("anchor", "unknown_anchor"),
    ],
)
async def test_invalid_batch_does_not_dispatch_or_charge(monkeypatch, case, reason):
    document, arguments = target(), patch()
    if case == "version":
        arguments["base_version"] = 1
    if case == "selection":
        arguments["insertions"][0]["after_id"] = "keep"
    if case == "id":
        arguments["insertions"][0]["block"]["block_id"] = "invented"
    if case == "anchor":
        document["block_ids"] = []
        arguments["insertions"][0]["after_id"] = "missing"
    remote = AsyncMock()
    monkeypatch.setattr(structure, "call", remote)
    with use_run_execution(
        PrivateRunResources(workspace_ref={"document_context": document})
    ) as execution:
        apply_document_tool_consent(execution)
        outcome = await structure.propose_structure(None, json.dumps(arguments))
        assert not outcome.succeeded and not outcome.charged
        assert json.loads(outcome.text)["error_code"] == reason
    remote.assert_not_awaited()


@pytest.mark.parametrize(
    "version,enabled", [(None, False), (1, False), (2, True), (2.0, False), (True, False)]
)
def test_structure_requires_backend_protocol_negotiation(version, enabled):
    document = {**target(), "patch_version": version}
    with use_run_execution(
        PrivateRunResources(workspace_ref={"document_context": document})
    ) as execution:
        apply_document_tool_consent(execution)
        assert execution.policy.flag("document_structure_enabled") is enabled
        names = {
            tool.name for tool in GeneralAgent({"model": "test-model"})._applicable_tools(None)
        }
        assert ("tex_propose_structure" in names) is enabled


@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai", "local"])
def test_structure_schema_compiles_in_existing_provider_protocol(provider):
    tools = _tools_to_openai([structure.tool])
    result = compile_toolset(
        tools,
        provider=provider,
        capabilities=GIGACHAT_TOOL_CAPABILITIES
        if provider == "gigachat"
        else OPENAI_TOOL_CAPABILITIES,
        tool_choice={"type": "function", "function": {"name": "tex_propose_structure"}},
    )
    assert result.canonical_names == ("tex_propose_structure",)
