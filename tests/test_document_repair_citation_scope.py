"""Layout/source repair cannot silently rewrite accepted evidence identity."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.client.protocol.capabilities import GIGACHAT_TOOL_CAPABILITIES
from service.domain.client.protocol.compiler import compile_toolset
from service.domain.documents.authoring import repair as authoring_repair
from service.domain.documents.evidence.bundle import build_document_evidence_bundle
from service.domain.documents.evidence.citations import CitationRegistry
from service.domain.documents.intent import deterministic_intent
from service.domain.documents.semantic.draft import DocumentDraft, DraftBlock
from service.domain.subagents.research import SourceRegistry


def _bundle():
    registry = SourceRegistry()
    for name in ("first", "second"):
        registry.add(
            url=f"https://example.test/{name}",
            title=name,
            content=f"{name.upper()}_REPAIR_EVIDENCE genuine source passage.",
            content_kind="page",
        )
    return build_document_evidence_bundle([], registry.artifact())


def _response(source_id):
    arguments = {
        "base_version": 1,
        "replacements": [
            {
                "block_id": "repair_block",
                "kind": "slide",
                "text": "Repaired",
                "source_id": source_id,
            }
        ],
    }
    function = SimpleNamespace(name="submit_document_patch", arguments=arguments)
    return SimpleNamespace(
        response=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(tool_calls=[SimpleNamespace(function=function)])
                )
            ]
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("before, after", [(1, 2), (1, 0), (None, 1)])
async def test_repair_cannot_swap_remove_or_add_block_citation(monkeypatch, before, after):
    bundle = _bundle()
    invoke = AsyncMock(return_value=_response(after))
    monkeypatch.setattr(authoring_repair, "invoke_model_call", invoke)
    draft = DocumentDraft(1, 1, "Report", (DraftBlock("repair_block", "slide", source_id=before),))
    repaired = await authoring_repair.repair_semantic_draft(
        deterministic_intent("Prepare a report"),
        draft,
        ["layout_overflow:repair_block"],
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=CitationRegistry(bundle.bibliography),
    )
    assert repaired is None


@pytest.mark.asyncio
async def test_repair_receives_only_existing_cited_evidence_and_preserves_other_blocks(monkeypatch):
    bundle = _bundle()
    invoke = AsyncMock(return_value=_response(1))
    monkeypatch.setattr(authoring_repair, "invoke_model_call", invoke)
    safe = DraftBlock("safe_block", "paragraph", text="Unchanged")
    draft = DocumentDraft(1, 1, "Report", (DraftBlock("repair_block", "slide", source_id=1), safe))
    repaired = await authoring_repair.repair_semantic_draft(
        deterministic_intent("Prepare a report"),
        draft,
        ["layout_overflow:repair_block"],
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=CitationRegistry(bundle.bibliography),
        evidence=bundle,
    )
    assert repaired is not None and repaired.version == 2
    assert repaired.blocks[1] is safe and repaired.cited_source_ids == frozenset({1})
    prompt = json.loads(invoke.call_args.kwargs["messages"][1]["content"])
    assert "FIRST_REPAIR_EVIDENCE" in prompt["evidence"]
    assert "SECOND_REPAIR_EVIDENCE" not in prompt["evidence"]
    schema = invoke.call_args.kwargs["tools"][0]["function"]["parameters"]["properties"][
        "replacements"
    ]["items"]
    assert schema["properties"]["source_id"]["enum"] == [0, 1]
    tool = invoke.call_args.kwargs["tools"][0]
    compiled = compile_toolset(
        [tool],
        provider="gigachat",
        capabilities=GIGACHAT_TOOL_CAPABILITIES,
        tool_choice={"type": "function", "function": {"name": "submit_document_patch"}},
    )
    assert compiled.max_calls_per_round == 1
    assert (
        authoring_repair.PATCH_TOOL["function"]["parameters"]["properties"]["replacements"][
            "items"
        ]["properties"]["source_id"].get("enum")
        is None
    )


@pytest.mark.asyncio
async def test_missing_evidence_refuses_repair_before_model_call(monkeypatch):
    bundle = _bundle()
    empty = build_document_evidence_bundle([], None)
    invoke = AsyncMock(return_value=_response(1))
    monkeypatch.setattr(authoring_repair, "invoke_model_call", invoke)
    result = await authoring_repair.repair_semantic_draft(
        deterministic_intent("Prepare a report"),
        DocumentDraft(1, 1, "Report", (DraftBlock("repair_block", "slide", source_id=1),)),
        ["layout_overflow:repair_block"],
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=CitationRegistry(bundle.bibliography),
        evidence=empty,
    )
    assert result is None
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_evidence_budget_refuses_repair_without_clipping_or_model_call(monkeypatch):
    sources = SourceRegistry(max_sources=12)
    for index in range(10):
        sources.add(
            url=f"https://example.test/{index}",
            title=f"Source {index}",
            content=f"Distinct source {index}. " + "bounded passage " * 200,
            content_kind="page",
        )
    bundle = build_document_evidence_bundle([], sources.artifact())
    draft = DocumentDraft(
        1,
        1,
        "Report",
        tuple(DraftBlock(f"slide_{index}", "slide", source_id=index) for index in range(1, 11)),
    )
    invoke = AsyncMock()
    monkeypatch.setattr(authoring_repair, "invoke_model_call", invoke)
    result = await authoring_repair.repair_semantic_draft(
        deterministic_intent("Prepare a report"),
        draft,
        ["layout_overflow"],
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=CitationRegistry(bundle.bibliography),
        evidence=bundle,
    )
    assert result is None
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_generation_runtime_forwards_owned_evidence_to_repair(monkeypatch):
    from service.domain.subagents import pdf_generation_runtime as runtime

    bundle = _bundle()
    draft = DocumentDraft(1, 1, "Report", (DraftBlock("repair_block", "slide", source_id=1),))
    repair = AsyncMock(return_value=draft)
    monkeypatch.setattr(runtime, "repair_semantic_draft", repair)
    marker = object()
    monkeypatch.setattr(runtime, "render_document", lambda *args, **kwargs: marker)
    run = runtime.DocumentGenerationRun(
        ref={},
        brief=deterministic_intent("Prepare a report"),
        model="GigaChat-2",
        project_path="report",
        scaffold_source="",
        citations=CitationRegistry(bundle.bibliography),
        evidence=bundle,
        draft=draft,
        diagnostics=["layout_overflow:repair_block"],
    )
    assert await run._author(execution=SimpleNamespace(provider_snapshot=None)) is marker
    assert repair.call_args.kwargs["evidence"] is bundle
