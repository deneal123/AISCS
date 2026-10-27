"""Opt-in no-LLM regression through the actual isolated compiler image."""

from __future__ import annotations

import importlib.util
import io
import os
import tarfile
from pathlib import Path

import pytest

from service.domain.documents import (
    CitationRegistry,
    DocumentDraft,
    DraftBlock,
    parse_document_intent,
    render_document,
)
from service.domain.subagents.research import ResearchArtifact, SourceRecord


@pytest.mark.skipif(
    os.environ.get("S37_LIVE_DOCUMENT_COMPILER") != "1", reason="opt-in Docker compiler"
)
def test_source_backed_article_table_equation_and_bibliography_compile(monkeypatch):
    """Synthetic evidence tests rendering, not authenticity or article acceptance."""
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "document_article_smoke", root / "scripts" / "smoke_document_runtime.py"
    )
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    original = smoke._source_archive
    intent = parse_document_intent(
        {
            "kind": "article",
            "profile_id": "generic_article",
            "locale": "ru-RU",
            "title": "Проверка статьи",
            "mode": "camera_ready",
        },
        request="Synthetic compiler acceptance",
    )
    assert intent is not None
    citations = CitationRegistry(
        ResearchArtifact(
            1,
            (
                SourceRecord(
                    source_id=1,
                    canonical_url="https://example.test/synthetic-reference",
                    title="Synthetic rendering fixture",
                    content="Synthetic source content.",
                    content_kind="page",
                    fingerprint="a" * 64,
                    authors=("Fixture Author",),
                    year=2025,
                ),
            ),
        )
    )
    rendered = render_document(
        intent,
        DocumentDraft(
            1,
            1,
            intent.title,
            (
                DraftBlock("abstract_section", "section", title="Аннотация"),
                DraftBlock("abstract_text", "paragraph", text="Синтетическая проверка вёрстки."),
                DraftBlock("intro_section", "section", title="Введение"),
                DraftBlock(
                    "source_claim", "citation", text="Проверяем механизм ссылок", source_id=1
                ),
                DraftBlock(
                    "sample_table",
                    "table",
                    title="Контрольная таблица",
                    columns=("Параметр", "Значение"),
                    rows=(("Число", "2"), ("Текст", "тест")),
                ),
                DraftBlock("sample_formula", "equation", text=r"x = \frac{1}{2}"),
                DraftBlock("conclusion_section", "section", title="Заключение"),
                DraftBlock(
                    "conclusion_text", "paragraph", text="Это fixture, не научный результат."
                ),
            ),
        ),
        scaffold_source=(smoke.PROFILE_ROOT / "generic_article" / "main.tex").read_text("utf-8"),
        citations=citations,
        bibliography=citations.bibliography(),
    )
    assert "src1_aaaaaaaaaa" in rendered.files["bibliography/references.bib"]

    def archive(profile_id, *, publication):
        base, profile = original(profile_id, publication=publication)
        output = io.BytesIO()
        with (
            tarfile.open(fileobj=io.BytesIO(base)) as source,
            tarfile.open(fileobj=output, mode="w") as target,
        ):
            for entry in source.getmembers():
                if entry.name not in rendered.files:
                    target.addfile(entry, source.extractfile(entry))
            for name, value in rendered.files.items():
                data = value.encode("utf-8")
                entry = tarfile.TarInfo(name)
                entry.size, entry.mode, entry.mtime = len(data), 0o444, 1_704_067_200
                target.addfile(entry, io.BytesIO(data))
        return output.getvalue(), profile

    monkeypatch.setattr(smoke, "_source_archive", archive)
    pages, size = smoke._smoke_profile(
        "gpthub-document-runtime:latest", "generic_article", publication=True
    )
    assert pages >= 1 and size > 1000


@pytest.mark.skipif(
    os.environ.get("S37_LIVE_DOCUMENT_COMPILER") != "1", reason="opt-in Docker compiler"
)
def test_article_without_sources_has_openable_preview_not_a_final(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "document_preview_smoke", root / "scripts" / "smoke_document_runtime.py"
    )
    assert spec is not None and spec.loader is not None
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    original = smoke._source_archive
    intent = parse_document_intent(
        {
            "kind": "article",
            "profile_id": "generic_article",
            "locale": "ru-RU",
            "title": "Проверка черновика",
        },
        request="Напиши статью по материалам без библиографических реквизитов",
    )
    assert intent is not None
    scaffold = (smoke.PROFILE_ROOT / "generic_article" / "main.tex").read_text("utf-8")
    rendered = render_document(
        intent,
        DocumentDraft(
            1,
            1,
            "Проверка черновика",
            (DraftBlock("material_body", "paragraph", text="Материал."),),
        ),
        scaffold_source=scaffold,
        enforce_evidence=False,
    )

    def archive(profile_id, *, publication):
        assert profile_id == "generic_article" and not publication
        base, profile = original(profile_id, publication=publication)
        output = io.BytesIO()
        with (
            tarfile.open(fileobj=io.BytesIO(base)) as source,
            tarfile.open(fileobj=output, mode="w") as target,
        ):
            for entry in source.getmembers():
                if entry.name not in rendered.files:
                    target.addfile(entry, source.extractfile(entry))
            for name, text in rendered.files.items():
                data = text.encode("utf-8")
                entry = tarfile.TarInfo(name)
                entry.size, entry.mode, entry.mtime = len(data), 0o444, 1_704_067_200
                target.addfile(entry, io.BytesIO(data))
        return output.getvalue(), profile

    monkeypatch.setattr(smoke, "_source_archive", archive)
    pages, size = smoke._smoke_profile(
        "gpthub-document-runtime:latest", "generic_article", publication=False
    )
    assert pages >= 1 and size > 1000
    print(f"document-preview-compiler: status=ready pages={pages} size={size}")
