"""Document sources preserve supplied metadata without inventing it from locators."""

from dataclasses import replace

import pytest

from service.domain.documents.evidence.bundle import build_document_evidence_bundle
from service.domain.documents.evidence.citations import CitationRegistry
from service.domain.subagents.research import ResearchArtifact, SourceRegistry


def attachment(content, *, digest=None):
    return {"file_id": "owned", "name": "materials.md", "content": content, "digest": digest}


def research(*, title="Registered source", authors=None, year=2024, doi="10.1234/verified"):
    registry = SourceRegistry()
    registry.add(
        url="https://example.test/paper",
        title=title,
        content="Retrieved source evidence retained for this article.",
        content_kind="page",
        authors=authors or ["A. Author"],
        year=year,
        doi=doi,
    )
    return registry.artifact()


@pytest.mark.parametrize(
    "content",
    [
        "DOI: 10.2020/example-paper",
        "[Registered source](https://doi.org/10.2021/example-paper)",
        "[Registered source](https://example.test/2022/paper)",
        "Provided source https://example.test/paper?version=2023",
        "[Observations during 2024](https://example.test/paper)",
    ],
)
def test_identifier_or_title_numbers_are_not_publication_year(content):
    bundle = build_document_evidence_bundle([attachment(content)], None)
    assert bundle.has_bibliography
    assert all(record.year is None for record in bundle.bibliography.records)


@pytest.mark.parametrize(
    "content,year",
    [
        ("A. Author, 2025. [Source](https://example.test/paper)", 2025),
        ("[Source](https://example.test/paper), 2019. DOI 10.2024/example", 2019),
        ("Year: 2018. DOI: 10.2023/example", 2018),
    ],
)
def test_explicit_bibliographic_year_outside_locator_is_preserved(content, year):
    bundle = build_document_evidence_bundle([attachment(content)], None)
    assert bundle.bibliography.records[0].year == year


def test_same_url_research_fills_missing_metadata_without_changing_citation_identity():
    material = attachment("[Provided source](https://example.test/paper)")
    original = build_document_evidence_bundle([material], None)
    combined = build_document_evidence_bundle([material], research())
    assert len(combined.bibliography.records) == 1
    record = combined.bibliography.records[0]
    assert record.authors == ("A. Author",) and record.year == 2024
    assert record.doi == "10.1234/verified"
    assert record.title == "Provided source"  # Do not overwrite explicit supplied fields.
    assert CitationRegistry(combined.bibliography).key_for(record.source_id) == CitationRegistry(
        original.bibliography
    ).key_for(record.source_id)


def test_conflicting_supplied_year_is_not_silently_overwritten_by_research():
    combined = build_document_evidence_bundle(
        [attachment("[Provided source](https://example.test/paper), 2020.")], research(year=2024)
    )
    assert combined.bibliography.records[0].year == 2020


def test_enrichment_does_not_mutate_input_research_artifact():
    artifact = research()
    before = artifact.records
    bundle = build_document_evidence_bundle(
        [attachment("[Provided](https://example.test/paper)")], artifact
    )
    assert artifact.records == before and bundle.research is artifact


def test_bundle_digest_binds_actual_extracted_material_even_with_same_owned_file_digest():
    original = build_document_evidence_bundle(
        [attachment("Original extracted material.", digest="a" * 64)], None
    )
    changed = build_document_evidence_bundle(
        [attachment("Changed extracted material.", digest="a" * 64)], None
    )
    assert original.digest != changed.digest
    assert original.attachments[0].source_id == changed.attachments[0].source_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", "Updated registered title"),
        ("authors", ("B. Author",)),
        ("year", 2025),
        ("doi", "10.1234/changed"),
        ("content", "Changed retrieved source evidence, same external fingerprint."),
    ],
)
def test_bundle_digest_binds_research_semantics_not_only_external_fingerprint(field, value):
    artifact = research()
    changed = ResearchArtifact(
        artifact.schema_version, (replace(artifact.records[0], **{field: value}),)
    )
    assert artifact.digest == changed.digest  # Existing research digest is not this binding seam.
    assert (
        build_document_evidence_bundle([], artifact).digest
        != build_document_evidence_bundle([], changed).digest
    )


def test_bundle_digest_and_summary_are_stable_and_private():
    marker = "PRIVATE_ARTICLE_EVIDENCE_METADATA_MARKER"
    data = [attachment(marker + "\n[Source](https://example.test/paper), 2024.")]
    first = build_document_evidence_bundle(data, research(title=marker))
    second = build_document_evidence_bundle(data, research(title=marker))
    assert first.digest == second.digest and len(first.digest) == 64
    assert marker not in repr(first.summary()) and "https://" not in repr(first.summary())
