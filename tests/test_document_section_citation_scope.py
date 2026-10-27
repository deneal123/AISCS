"""A registered-but-unseen citation cannot be substituted into a section."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.client.protocol.capabilities import GIGACHAT_TOOL_CAPABILITIES
from service.domain.client.protocol.compiler import compile_toolset
from service.domain.documents.authoring import execution as authoring
from service.domain.documents.authoring.protocol import compile_section_tool
from service.domain.documents.evidence.bundle import build_document_evidence_bundle
from service.domain.documents.evidence.citations import CitationRegistry
from service.domain.documents.evidence.mentions import referenced_citations
from service.domain.documents.intent import deterministic_intent
from service.domain.documents.semantic.outline import DocumentOutline, DocumentOutlineSection
from service.domain.subagents.research import SourceRegistry


def _bundle(material=None):
    sources = SourceRegistry()
    for name in ("first", "second"):
        sources.add(
            url=f"https://example.test/{name}",
            title=name,
            content=f"{name.upper()}_REGISTERED_BODY contains actual source evidence.",
            content_kind="page",
        )
    return build_document_evidence_bundle(
        [{"name": "materials.md", "content": material}] if material else [], sources.artifact()
    )


def _section(source_ids):
    section = DocumentOutlineSection(
        "section", "Раздел", "Обзор", ("paragraph", "citation"), source_ids
    )
    return section, DocumentOutline("Документ", (section,))


def _response(source_id):
    arguments = {
        "blocks": [
            {"kind": "paragraph", "text": "Source-backed paragraph.", "source_id": source_id}
        ]
    }
    function = SimpleNamespace(name="submit_document_section", arguments=json.dumps(arguments))
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
async def test_section_schema_and_prompt_offer_only_visible_registered_citations(monkeypatch):
    bundle = _bundle()
    section, outline = _section(("2",))
    invoke = AsyncMock(return_value=_response(2))
    monkeypatch.setattr(authoring, "invoke_model_call", invoke)
    blocks, failure, _ = await authoring._invoke_section_round(
        deterministic_intent("Подготовь отчет"),
        outline,
        section,
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=CitationRegistry(bundle.bibliography),
        evidence=bundle,
        repair=False,
    )
    assert blocks is not None and failure is None
    payload = invoke.call_args.kwargs
    schema = payload["tools"][0]["function"]["parameters"]["properties"]["blocks"]["items"][
        "properties"
    ]
    assert schema["source_id"]["enum"] == [0, 2]
    assert json.loads(payload["messages"][1]["content"])["registered_citation_ids"] == [2]


@pytest.mark.asyncio
async def test_model_cannot_substitute_a_different_registered_source(monkeypatch):
    bundle = _bundle()
    section, outline = _section(("2",))
    monkeypatch.setattr(authoring, "invoke_model_call", AsyncMock(return_value=_response(1)))
    blocks, failure, reason = await authoring._invoke_section_round(
        deterministic_intent("Подготовь отчет"),
        outline,
        section,
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=CitationRegistry(bundle.bibliography),
        evidence=bundle,
        repair=False,
    )
    assert blocks is None and failure == reason == "citation_unknown"


def test_material_citation_link_resolves_to_registered_body_not_unrelated_source():
    bundle = _bundle("Сведения по [источнику](https://example.test/first).")
    source = bundle.attachments[0].chunks[0].source_id
    section, outline = _section((source,))
    prompt = json.loads(
        authoring._section_prompt(
            deterministic_intent("Подготовь отчет"),
            outline,
            section,
            CitationRegistry(bundle.bibliography),
            bundle,
        )
    )
    assert "Источник [1]" in prompt["evidence"]
    assert "FIRST_REGISTERED_BODY" in prompt["evidence"]
    assert "SECOND_REGISTERED_BODY" not in prompt["evidence"]
    assert prompt["registered_citation_ids"] == [1]


@pytest.mark.parametrize(
    "locator, expected",
    [
        ("https://EXAMPLE.test/first?utm_source=fixture#part", frozenset({1})),
        ("https://example.test/first-extra", frozenset()),
        ("https://example.test/first/other", frozenset()),
        ("https://example.test.evil.test/first", frozenset()),
        ("https://unknown.test/article", frozenset()),
    ],
)
def test_material_locators_match_only_canonical_registered_sources(locator, expected):
    assert referenced_citations(locator, _bundle().bibliography.records) == expected


def test_explicit_doi_matches_registered_metadata_without_inference():
    records = _bundle().bibliography.records
    first = replace(records[0], doi="10.1234/REAL-RECORD")
    assert referenced_citations("DOI: 10.1234/real-record.", (first,)) == frozenset({1})
    assert referenced_citations("DOI: 10.1234/real-record-other", (first,)) == frozenset()


def test_truncated_or_unresolved_blocks_never_offer_citation_ids():
    bundle = _bundle()
    truncated = bundle.project_context(max_chars=10, source_ids=("2",))
    assert not truncated.complete and not truncated.citation_ids
    unresolved = bundle.project_context(max_chars=18_000, source_ids=("unknown",))
    assert not unresolved.complete and not unresolved.citation_ids


def test_projection_does_not_modify_registry_or_expose_source_in_repr():
    bundle = _bundle()
    before = (bundle.digest, bundle.bibliography.records)
    projection = bundle.project_context(max_chars=18_000, source_ids=("2",))
    assert projection.citation_ids == frozenset({2})
    assert (bundle.digest, bundle.bibliography.records) == before
    assert "SECOND_REGISTERED_BODY" not in repr(projection)
    assert "citation_ids" not in repr(projection)


@pytest.mark.parametrize("source_ids", [frozenset(), frozenset({2})])
def test_scoped_section_schema_preserves_strict_gigachat_constraints(source_ids):
    tool = compile_section_tool(source_ids, frozenset({"paragraph", "citation"}))
    compiled = compile_toolset(
        [tool],
        provider="gigachat",
        capabilities=GIGACHAT_TOOL_CAPABILITIES,
        tool_choice={"type": "function", "function": {"name": "submit_document_section"}},
    )
    source_schema = compiled.functions[0]["parameters"]["properties"]["blocks"]["items"][
        "properties"
    ]["source_id"]
    assert source_schema["enum"] == [0, *sorted(source_ids)]
    assert compiled.max_calls_per_round == 1


@pytest.mark.asyncio
async def test_wrong_source_has_only_one_protocol_repair_without_scope_widening(monkeypatch):
    bundle = _bundle()
    _, outline = _section(("2",))
    invoke = AsyncMock(return_value=_response(1))
    monkeypatch.setattr(authoring, "invoke_model_call", invoke)
    monkeypatch.setattr(
        authoring, "_outline_with_single_repair", AsyncMock(return_value=(outline, False, None))
    )
    checkpoint = AsyncMock()
    result = await authoring.author_semantic_draft_result(
        deterministic_intent("Prepare a report"),
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=CitationRegistry(bundle.bibliography),
        evidence=bundle,
        checkpoint=checkpoint,
    )
    assert result.draft is None and result.failure_code == "citation_unknown"
    assert result.repair_used and invoke.await_count == 2
    assert checkpoint.await_count >= 1
    for call in invoke.await_args_list:
        prompt = json.loads(call.kwargs["messages"][1]["content"])
        assert prompt["registered_citation_ids"] == [2]
