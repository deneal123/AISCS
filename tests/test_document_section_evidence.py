"""Section prompts use selected source bodies and the final bibliography namespace."""

import json

import pytest

from service.domain.documents.authoring.execution import _section_prompt
from service.domain.documents.evidence import bundle as bundle_module
from service.domain.documents.evidence.bundle import build_document_evidence_bundle
from service.domain.documents.evidence.citations import CitationRegistry
from service.domain.documents.intent import deterministic_intent
from service.domain.documents.semantic.outline import DocumentOutline, DocumentOutlineSection
from service.domain.subagents.research import SourceRegistry


def _prompt(bundle, source_ids):
    section = DocumentOutlineSection("section", "Раздел", "Обзор", ("paragraph",), source_ids)
    return json.loads(
        _section_prompt(
            deterministic_intent("Подготовь отчет"),
            DocumentOutline("Отчет", (section,)),
            section,
            CitationRegistry(bundle.bibliography),
            bundle,
        )
    )["evidence"]


def test_late_selected_material_is_not_replaced_by_the_first_attachment_prefix():
    bundle = build_document_evidence_bundle(
        [
            {"content": "EARLY_MATERIAL " * 2400, "name": "first.md"},
            {
                "content": "LATE_SELECTED_MATERIAL retained for the final section.",
                "name": "last.md",
            },
        ],
        None,
    )
    source = bundle.attachments[-1].chunks[0].source_id
    prompt = _prompt(bundle, (source,))
    assert "LATE_SELECTED_MATERIAL" in prompt
    assert "EARLY_MATERIAL" not in prompt
    assert source in prompt


def test_research_ids_are_remapped_to_the_registered_bibliography_namespace():
    registry = SourceRegistry()
    registry.add(
        url="https://example.test/research",
        title="Retrieved source",
        content="RETRIEVED_SOURCE_BODY is independent evidence.",
        content_kind="page",
    )
    bundle = build_document_evidence_bundle(
        [
            {
                "content": "[Provided source](https://example.test/attachment), 2024.",
                "name": "first.md",
            }
        ],
        registry.artifact(),
    )
    assert bundle.research.records[0].source_id == 1
    assert bundle.bibliography.records[1].source_id == 2
    prompt = bundle.prompt_context()
    assert "Источник [2]\nНазвание: Retrieved source\nМатериал: RETRIEVED_SOURCE_BODY" in prompt
    assert "Источник [1]\nНазвание: Retrieved source" not in prompt


def test_selected_citation_uses_retrieved_body_even_when_supplied_metadata_was_first():
    registry = SourceRegistry()
    registry.add(
        url="https://example.test/source",
        title="Retrieved title",
        content="ACTUAL_RESEARCH_BODY with independently retrieved evidence.",
        content_kind="page",
    )
    bundle = build_document_evidence_bundle(
        [{"content": "[Provided title](https://example.test/source)", "name": "first.md"}],
        registry.artifact(),
    )
    before = bundle.digest
    prompt = _prompt(bundle, ("1",))
    assert "Источник [1]" in prompt
    assert "ACTUAL_RESEARCH_BODY" in prompt
    assert "Название: Provided title" in prompt
    assert bundle.digest == before


def test_selected_registered_citation_does_not_receive_unrelated_materials():
    registry = SourceRegistry()
    registry.add(
        url="https://example.test/research",
        title="Retrieved source",
        content="SELECTED_RESEARCH_BODY is independent evidence.",
        content_kind="page",
    )
    bundle = build_document_evidence_bundle(
        [
            {
                "content": "UNRELATED_MATERIAL [Provided](https://example.test/first)",
                "name": "first.md",
            }
        ],
        registry.artifact(),
    )
    prompt = _prompt(bundle, ("2",))
    assert "SELECTED_RESEARCH_BODY" in prompt
    assert "UNRELATED_MATERIAL" not in prompt
    assert "Источник [1]" not in prompt


@pytest.mark.parametrize("selection", [(), ("unknown-private-target",)])
def test_explicit_empty_or_unknown_source_selection_does_not_disclose_the_full_bundle(selection):
    bundle = build_document_evidence_bundle(
        [{"name": "secret.md", "content": "PRIVATE_UNSELECTED_BODY retained in Workspace"}], None
    )
    assert bundle.prompt_context(source_ids=selection) == ""
    assert "PRIVATE_UNSELECTED_BODY" not in repr(bundle.summary())


@pytest.mark.parametrize("limit", [0, 100, 256, 1000, 4000, 9000])
def test_bounded_projection_counts_separators_and_preserves_digest(limit):
    bundle = build_document_evidence_bundle(
        [{"name": "long.md", "content": "Actual source paragraph. " * 900}], None
    )
    digest = bundle.digest
    assert len(bundle.prompt_context(max_chars=limit)) <= limit
    assert bundle.digest == digest


def test_projection_version_invalidates_old_resume_binding_without_renumbering_sources(monkeypatch):
    materials = [{"name": "first.md", "content": "[Provided source](https://example.test/paper)"}]
    original = build_document_evidence_bundle(materials, None)
    monkeypatch.setattr(
        bundle_module, "EVIDENCE_PROJECTION_VERSION", bundle_module.EVIDENCE_PROJECTION_VERSION + 1
    )
    updated = build_document_evidence_bundle(materials, None)
    assert updated.digest != original.digest
    assert updated.attachments == original.attachments
    assert updated.bibliography == original.bibliography
