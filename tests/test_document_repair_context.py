"""Local repairs remain bounded without replacing unaffected document content."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.documents.authoring import repair as authoring_repair
from service.domain.documents.evidence.bundle import build_document_evidence_bundle
from service.domain.documents.evidence.citations import CitationRegistry
from service.domain.documents.intent import deterministic_intent
from service.domain.documents.semantic.draft import DocumentDraft, DraftBlock
from service.domain.subagents.research import SourceRegistry


def _response(block):
    function = SimpleNamespace(
        name="submit_document_patch", arguments={"base_version": 1, "replacements": [block]}
    )
    return SimpleNamespace(
        response=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(tool_calls=[SimpleNamespace(function=function)])
                )
            ]
        )
    )


async def _repair(draft, diagnostics, **kwargs):
    return await authoring_repair.repair_semantic_draft(
        deterministic_intent("Prepare a report"),
        draft,
        diagnostics,
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_targeted_repair_avoids_unrelated_evidence_and_large_body(monkeypatch):
    registry = SourceRegistry(max_sources=12)
    for index in range(1, 11):
        registry.add(
            url=f"https://example.test/{index}",
            title=f"Source {index}",
            content=f"Unique {index}. " + "passage " * 400,
            content_kind="page",
        )
    bundle = build_document_evidence_bundle([], registry.artifact())
    target = DraftBlock("repair_block", "slide", source_id=1)
    others = tuple(DraftBlock(f"slide_{index}", "slide", source_id=index) for index in range(2, 11))
    large = DraftBlock("large_block", "paragraph", text="UNRELATED_BODY " * 6000)
    draft = DocumentDraft(1, 1, "Report", (target, *others, large))
    invoke = AsyncMock(
        return_value=_response(
            {"block_id": "repair_block", "kind": "slide", "source_id": 1, "text": "Repaired"}
        )
    )
    monkeypatch.setattr(authoring_repair, "invoke_model_call", invoke)
    result = await _repair(
        draft,
        ["layout_overflow:repair_block"],
        citations=CitationRegistry(bundle.bibliography),
        evidence=bundle,
    )
    assert result is not None and result.blocks[1:] == draft.blocks[1:]
    prompt = json.loads(invoke.call_args.kwargs["messages"][1]["content"])
    assert [block["block_id"] for block in prompt["draft"]["blocks"]] == ["repair_block"]
    assert "UNRELATED_BODY" not in invoke.call_args.kwargs["messages"][1]["content"]
    schema = invoke.call_args.kwargs["tools"][0]["function"]["parameters"]["properties"][
        "replacements"
    ]["items"]["properties"]
    assert schema["source_id"]["enum"] == [0, 1]


@pytest.mark.asyncio
async def test_oversized_target_refuses_before_paid_call(monkeypatch):
    draft = DocumentDraft(
        1, 1, "Report", (DraftBlock("repair_block", "paragraph", text="large " * 15_000),)
    )
    invoke = AsyncMock(
        return_value=_response(
            {"block_id": "repair_block", "kind": "paragraph", "text": "Repaired"}
        )
    )
    monkeypatch.setattr(authoring_repair, "invoke_model_call", invoke)
    assert await _repair(draft, ["layout_overflow:repair_block"]) is None
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_long_block_id_is_not_clipped_into_global_repair(monkeypatch):
    identifier = "repair_" + "a" * 57
    draft = DocumentDraft(
        1,
        1,
        "Report",
        (DraftBlock(identifier, "paragraph"), DraftBlock("safe_block", "paragraph", text="Keep")),
    )
    invoke = AsyncMock(
        return_value=_response({"block_id": "safe_block", "kind": "paragraph", "text": "Unwanted"})
    )
    monkeypatch.setattr(authoring_repair, "invoke_model_call", invoke)
    assert await _repair(draft, [f"layout_overflow:{identifier}"]) is None


@pytest.mark.asyncio
async def test_unknown_target_does_not_fall_back_to_global_repair(monkeypatch):
    draft = DocumentDraft(1, 1, "Report", (DraftBlock("safe_block", "paragraph", text="Keep"),))
    invoke = AsyncMock(
        return_value=_response({"block_id": "safe_block", "kind": "paragraph", "text": "Unwanted"})
    )
    monkeypatch.setattr(authoring_repair, "invoke_model_call", invoke)
    assert await _repair(draft, ["layout_overflow:unknown_block"]) is None
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_paragraph_repair_retains_immediately_following_citation_evidence(monkeypatch):
    registry = SourceRegistry()
    registry.add(
        url="https://example.test/first",
        title="First",
        content="BOUND_PARAGRAPH_SOURCE actual evidence.",
        content_kind="page",
    )
    bundle = build_document_evidence_bundle([], registry.artifact())
    paragraph = DraftBlock("repair_block", "paragraph", text="Source-backed paragraph")
    citation = DraftBlock("source_reference", "citation", source_id=1)
    draft = DocumentDraft(1, 1, "Report", (paragraph, citation))
    invoke = AsyncMock(
        return_value=_response(
            {"block_id": "repair_block", "kind": "paragraph", "text": "Repaired"}
        )
    )
    monkeypatch.setattr(authoring_repair, "invoke_model_call", invoke)
    result = await _repair(
        draft,
        ["layout_overflow:repair_block"],
        citations=CitationRegistry(bundle.bibliography),
        evidence=bundle,
    )
    assert result is not None and result.blocks[1] is citation
    prompt = json.loads(invoke.call_args.kwargs["messages"][1]["content"])
    assert "BOUND_PARAGRAPH_SOURCE" in prompt["evidence"]
