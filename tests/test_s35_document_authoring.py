from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from service.domain.documents import (
    DOCUMENT_SKILL_CATALOG,
    CitationRegistry,
    DocumentDraft,
    DocumentIntent,
    DraftBlock,
    DraftPatch,
    apply_draft_patch,
    authoring_repair,
    literal_draft,
    literal_shortcut,
    parse_document_draft,
    parse_document_intent,
    render_document,
    repair_semantic_draft,
)
from service.domain.subagents import pdf_generation, pdf_generation_runtime
from service.domain.subagents.research import (
    ResearchArtifact,
    SourceRecord,
    artifact_from_external_sources,
)

SCAFFOLD = r"""\documentclass[11pt,a4paper]{article}
\usepackage{fontspec}
\usepackage{tabularx}
\usepackage{booktabs}
\title{Old title}
\begin{document}
old body
\end{document}
"""


def _intent(**changes) -> DocumentIntent:
    values = {
        "schema_version": 1,
        "request": "Создай документ",
        "kind": "generic",
        "profile_id": "generic_document",
        "locale": "ru-RU",
        "mode": "camera_ready",
        "title": "Проверка",
        "audience": "пользователь",
        "length_class": "short",
        "required_sections": (),
        "citation_policy": "none",
        "presentation_density": "balanced",
        "legal_fields": (),
        "user_requirements": (),
    }
    values.update(changes)
    return DocumentIntent(**values)


def test_exact_literal_shortcut_is_deterministic_and_escaped() -> None:
    intent = literal_shortcut('Создай PDF и напиши "тест & 2"')
    assert intent is not None
    assert intent.literal_text == "тест & 2"

    rendered = render_document(
        intent,
        literal_draft(intent.literal_text),
        scaffold_source=SCAFFOLD,
    )

    assert "тест \\& 2" in rendered.files["content/001-literal_text.tex"]
    assert "\\input{content/001-literal_text.tex}" in rendered.files["main.tex"]
    assert "\\maketitle" not in rendered.files["main.tex"]
    assert "\\thispagestyle{empty}" in rendered.files["main.tex"]
    assert "\\begin{center}\\Large" in rendered.files["main.tex"]
    assert "old body" not in rendered.files["main.tex"]
    assert rendered.authoring_version == 1
    assert len(rendered.draft_digest) == 64
    manifest = json.loads(rendered.files[".gpthub-authoring.json"])
    assert manifest["draft"]["blocks"][0]["block_id"] == "literal_text"


def test_document_skill_catalog_digest_covers_the_editorial_contract() -> None:
    manifest = DOCUMENT_SKILL_CATALOG.safe_manifest()

    assert manifest["version"] == "s35.v1"
    assert manifest["count"] == 7
    assert len(str(manifest["digest"])) == 64


def test_profile_required_sections_cannot_be_removed_by_model_intent() -> None:
    intent = parse_document_intent(
        {
            "kind": "article",
            "profile_id": "generic_article",
            "locale": "ru-RU",
            "mode": "submission",
            "title": "Обзор",
            "audience": "читатели",
            "length_class": "short",
            "required_sections": ["Методы"],
            "citation_policy": "required",
            "presentation_density": "balanced",
            "legal_fields": [],
            "user_requirements": [],
        },
        "Напиши обзор",
    )

    assert intent is not None
    assert intent.required_sections == (
        "Аннотация",
        "Введение",
        "Заключение",
        "Литература",
        "Методы",
    )


def test_model_section_aliases_cannot_duplicate_locked_profile_sections() -> None:
    intent = parse_document_intent(
        {
            "kind": "article",
            "profile_id": "generic_article",
            "locale": "ru-RU",
            "mode": "submission",
            "title": "Обзор",
            "audience": "читатели",
            "length_class": "short",
            "required_sections": [
                "abstract",
                "introduction",
                "body",
                "conclusion",
                "bibliography",
                "Methods",
            ],
            "citation_policy": "required",
            "presentation_density": "balanced",
            "legal_fields": [],
            "user_requirements": [],
        },
        "Напиши обзор",
    )

    assert intent is not None
    assert intent.required_sections == (
        "Аннотация",
        "Введение",
        "Заключение",
        "Литература",
        "Methods",
    )


def test_renderer_restores_profile_sections_removed_by_a_late_repair() -> None:
    required = ("Abstract", "Introduction", "Conclusion", "References")
    intent = _intent(
        kind="article",
        profile_id="ieee_journal",
        required_sections=required,
        citation_policy="required",
    )
    draft = DocumentDraft(
        1,
        4,
        "Review",
        (DraftBlock("body_text", "paragraph", text="Accepted evidence-backed body."),),
    )

    rendered = render_document(
        intent,
        draft,
        scaffold_source=SCAFFOLD,
        enforce_evidence=False,
    )
    manifest = json.loads(rendered.files[".gpthub-authoring.json"])
    headings = {
        block["title"] for block in manifest["draft"]["blocks"] if block["kind"] == "section"
    }

    assert headings == set(required)
    assert rendered.draft_digest == manifest["draft_digest"]
    assert all(
        any(
            f"\\{command}{{{title}}}" in source
            for command in ("section",)
            for source in rendered.files.values()
        )
        or (
            title == "Abstract"
            and any("\\begin{abstract}" in source for source in rendered.files.values())
        )
        for title in required
        if title != "References"
    )
    references_block = next(
        block
        for block in manifest["draft"]["blocks"]
        if block["kind"] == "section" and block["title"] == "References"
    )
    references_path = next(
        path
        for path, block_id in manifest["block_files"].items()
        if block_id == references_block["block_id"]
    )
    assert rendered.files[references_path].strip() == ""


def test_legacy_pptx_agent_is_not_exported_as_an_active_subagent() -> None:
    from service.domain import subagents

    assert "PPTXGenerationAgent" not in subagents.__all__


def test_legacy_pptx_http_compatibility_does_not_import_the_renderer() -> None:
    from service.presentation.routers.capabilities import tools

    names = tools.pptx_tool.__code__.co_names
    assert "generate_pptx" not in names
    assert "list_qualified_models" not in names


def test_semantic_draft_rejects_duplicate_ids_and_unknown_citations() -> None:
    raw = {
        "title": "Article",
        "version": 1,
        "blocks": [
            {
                "block_id": "same_id",
                "kind": "paragraph",
                "title": "",
                "text": "One",
                "items": [],
                "columns": [],
                "rows": [],
                "source_id": 0,
                "asset_path": "",
                "level": 1,
            },
            {
                "block_id": "same_id",
                "kind": "paragraph",
                "title": "",
                "text": "Two",
                "items": [],
                "columns": [],
                "rows": [],
                "source_id": 0,
                "asset_path": "",
                "level": 1,
            },
        ],
    }
    assert parse_document_draft(raw) is None

    raw["blocks"] = [
        {
            "block_id": "citation_without_source",
            "kind": "citation",
            "title": "",
            "text": "Claim",
            "items": [],
            "columns": [],
            "rows": [],
            "source_id": 0,
            "asset_path": "",
            "level": 1,
        }
    ]
    assert parse_document_draft(raw) is None

    raw["blocks"][0]["kind"] = "paragraph"
    raw["blocks"][0]["source_id"] = 7
    assert parse_document_draft(raw) is None

    raw["blocks"][0]["source_id"] = 0
    raw["blocks"][0]["asset_path"] = "figures/../../document.toml"
    assert parse_document_draft(raw) is None


def test_bibliography_uses_only_registered_source_ids() -> None:
    source = SourceRecord(
        source_id=1,
        canonical_url="https://example.test/paper?a=1&b=2",
        title="Verified paper & appendix_1",
        content="A retrieved fragment with sufficient evidence.",
        content_kind="page",
        fingerprint="a" * 64,
        authors=("A. Author",),
        year=2025,
        doi="10.1000/example",
    )
    citations = CitationRegistry(ResearchArtifact(1, (source,)))
    intent = _intent(
        kind="article",
        profile_id="generic_article",
        citation_policy="required",
    )
    draft = DocumentDraft(
        1,
        1,
        "Evidence article",
        (
            DraftBlock("intro_section", "section", title="Introduction"),
            DraftBlock("claim_source", "citation", text="Supported claim", source_id=1),
        ),
    )
    rendered = render_document(
        intent,
        draft,
        scaffold_source=SCAFFOLD.replace(
            "\\usepackage{tabularx}",
            "\\usepackage{tabularx}\n\\usepackage[backend=biber]{biblatex}",
        ),
        citations=citations,
        bibliography=citations.bibliography(),
    )
    assert "\\cite{src1_aaaaaaaaaa}" in rendered.files["content/002-claim_source.tex"]
    assert "Verified paper" in rendered.files["bibliography/references.bib"]
    assert "10.1000/example" in rendered.files["bibliography/references.bib"]
    assert "paper?a=1\\&b=2" in rendered.files["bibliography/references.bib"]
    assert "appendix\\_1" in rendered.files["bibliography/references.bib"]


def test_external_research_title_without_retrieved_fragment_is_not_evidence() -> None:
    artifact = artifact_from_external_sources(
        [{"title": "Metadata only", "url": "https://example.test/metadata"}]
    )

    assert artifact.status == "empty"
    assert artifact.records == ()


def test_research_artifact_requires_citations_for_report_and_presentation() -> None:
    source = SourceRecord(
        source_id=1,
        canonical_url="https://example.test/evidence",
        title="Evidence",
        content="A sufficiently long retrieved evidence fragment.",
        content_kind="page",
        fingerprint="d" * 64,
    )
    citations = CitationRegistry(ResearchArtifact(1, (source,)))

    report = pdf_generation._bind_evidence_policy(
        _intent(kind="report", profile_id="generic_report", citation_policy="none"),
        citations,
    )
    presentation = pdf_generation._bind_evidence_policy(
        _intent(kind="presentation", profile_id="beamer_16_9", citation_policy="none"),
        citations,
    )

    assert report.citation_policy == "required"
    assert presentation.citation_policy == "required"


def test_repair_replaces_only_existing_blocks_and_preserves_order() -> None:
    draft = DocumentDraft(
        1,
        4,
        "Stable",
        (
            DraftBlock("first_block", "paragraph", text="unchanged"),
            DraftBlock("second_block", "paragraph", text="too long"),
        ),
    )
    patched = apply_draft_patch(
        draft,
        DraftPatch(4, (DraftBlock("second_block", "paragraph", text="short"),)),
    )
    assert patched is not None
    assert patched.version == 5
    assert [block.block_id for block in patched.blocks] == ["first_block", "second_block"]
    assert patched.blocks[0] is draft.blocks[0]
    assert patched.blocks[1].text == "short"


def test_article_without_evidence_is_not_rendered_as_final_source() -> None:
    intent = _intent(
        kind="article",
        profile_id="generic_article",
        citation_policy="required",
    )
    draft = DocumentDraft(
        1, 1, "No evidence", (DraftBlock("body_text", "paragraph", text="Claim"),)
    )
    try:
        render_document(intent, draft, scaffold_source=SCAFFOLD)
    except ValueError as exc:
        assert str(exc) == "evidence_required"
    else:
        raise AssertionError("article final must require evidence")


def test_unsupported_intent_cannot_fall_back_to_arbitrary_latex() -> None:
    intent = parse_document_intent(
        {
            "kind": "unsupported",
            "profile_id": "generic_document",
            "locale": "ru-RU",
            "mode": "camera_ready",
            "title": "Unknown format",
            "audience": "reader",
            "length_class": "short",
            "required_sections": [],
            "citation_policy": "none",
            "presentation_density": "balanced",
            "legal_fields": [],
            "user_requirements": [],
        },
        "Create an unsupported arbitrary format",
    )

    assert intent is not None
    assert intent.kind == "unsupported"
    assert intent.mode == "draft"
    try:
        render_document(intent, literal_draft("editable"), scaffold_source=SCAFFOLD)
    except ValueError as exc:
        assert str(exc) == "authoring_unsupported"
    else:
        raise AssertionError("unsupported format must not generate model-authored LaTeX")


def test_evidence_deferred_render_keeps_an_editable_citation_placeholder() -> None:
    intent = _intent(
        kind="article",
        profile_id="generic_article",
        citation_policy="required",
    )
    draft = DocumentDraft(
        1,
        1,
        "Draft",
        (DraftBlock("claim_source", "citation", text="Claim", source_id=7),),
    )

    rendered = render_document(
        intent,
        draft,
        scaffold_source=SCAFFOLD,
        enforce_evidence=False,
    )

    assert "Citation source required" in rendered.files["content/001-claim_source.tex"]
    assert "\\cite{" not in rendered.files["content/001-claim_source.tex"]


def test_renderer_preserves_vendor_bibliography_style_and_adds_required_packages() -> None:
    source = SourceRecord(
        source_id=1,
        canonical_url="https://example.test/paper",
        title="Verified paper",
        content="A retrieved fragment with sufficient evidence.",
        content_kind="page",
        fingerprint="b" * 64,
    )
    citations = CitationRegistry(ResearchArtifact(1, (source,)))
    intent = _intent(kind="article", profile_id="ieee_journal", citation_policy="required")
    draft = DocumentDraft(
        1,
        1,
        "IEEE draft",
        (DraftBlock("claim_source", "citation", text="Claim", source_id=1),),
    )

    rendered = render_document(
        intent,
        draft,
        scaffold_source=(
            "\\documentclass[journal]{IEEEtran}\n"
            "\\usepackage{cite}\n"
            "\\begin{document}\nold\n\\end{document}\n"
        ),
        citations=citations,
        bibliography=citations.bibliography(),
    )

    assert "\\bibliographystyle{IEEEtran}" in rendered.files["main.tex"]
    assert "\\usepackage{tabularx}" in rendered.files["main.tex"]
    assert "\\usepackage{longtable}" in rendered.files["main.tex"]


def test_renderer_supports_long_tables_and_tables_inside_beamer_frames() -> None:
    rows = tuple((str(index), f"value {index}") for index in range(25))
    table = DraftBlock(
        "results_table",
        "table",
        title="Results",
        columns=("Index", "Value"),
        rows=rows,
    )
    article = render_document(
        _intent(kind="report", profile_id="generic_report"),
        DocumentDraft(1, 1, "Report", (table,)),
        scaffold_source=SCAFFOLD,
    )
    assert "\\begin{longtable}" in article.files["content/001-results_table.tex"]

    slide = DraftBlock(
        "summary_slide",
        "slide",
        title="Summary",
        columns=("Metric", "Value"),
        rows=(("Quality", "High"),),
    )
    presentation = render_document(
        _intent(kind="presentation", profile_id="beamer_16_9"),
        DocumentDraft(1, 1, "Deck", (slide,)),
        scaffold_source=(
            "\\documentclass[aspectratio=169]{beamer}\n\\begin{document}\nold\n\\end{document}\n"
        ),
    )
    body = presentation.files["content/001-summary_slide.tex"]
    assert "\\begin{frame}{Summary}" in body
    assert "\\begin{tabularx}" in body
    assert "\\begin{table}" not in body


def test_research_slide_uses_only_registered_evidence_and_adds_references_frame() -> None:
    source = SourceRecord(
        source_id=1,
        canonical_url="https://example.test/source",
        title="Verified source",
        content="Evidence collected by the research stage.",
        content_kind="page",
        fingerprint="c" * 64,
    )
    citations = CitationRegistry(ResearchArtifact(1, (source,)))
    raw = {
        "title": "Evidence deck",
        "version": 1,
        "blocks": [
            {
                "block_id": "evidence_slide",
                "kind": "slide",
                "title": "Result",
                "text": "Supported conclusion",
                "items": [],
                "columns": [],
                "rows": [],
                "source_id": 1,
                "asset_path": "",
                "level": 1,
            }
        ],
    }
    draft = parse_document_draft(raw)
    assert draft is not None

    rendered = render_document(
        _intent(kind="presentation", profile_id="beamer_16_9"),
        draft,
        scaffold_source=(
            "\\documentclass[aspectratio=169]{beamer}\n\\begin{document}\nold\n\\end{document}\n"
        ),
        citations=citations,
        bibliography=citations.bibliography(),
    )

    assert "\\cite{src1_cccccccccc}" in rendered.files["content/001-evidence_slide.tex"]
    assert "\\begin{frame}[allowframebreaks]{References}" in rendered.files["main.tex"]


def test_article_abstract_and_section_body_are_rendered_semantically() -> None:
    draft = DocumentDraft(
        1,
        1,
        "Article",
        (
            DraftBlock("abstract_block", "section", title="Abstract", text="Summary"),
            DraftBlock("method_block", "section", title="Method", text="Procedure"),
        ),
    )
    rendered = render_document(
        _intent(kind="article", profile_id="generic_article", citation_policy="optional"),
        draft,
        scaffold_source=SCAFFOLD,
    )

    assert (
        "\\begin{abstract}\nSummary\n\\end{abstract}"
        in rendered.files["content/001-abstract_block.tex"]
    )
    assert "\\section{Method}\nProcedure" in rendered.files["content/002-method_block.tex"]


def test_equation_renderer_rejects_file_read_primitives() -> None:
    draft = DocumentDraft(
        1,
        1,
        "Unsafe",
        (DraftBlock("unsafe_equation", "equation", text=r"\input{/etc/passwd}"),),
    )

    with pytest.raises(ValueError, match="authoring_unsupported"):
        render_document(_intent(), draft, scaffold_source=SCAFFOLD)


@pytest.mark.asyncio
async def test_article_without_registered_evidence_publishes_draft_before_blocking(
    monkeypatch,
) -> None:
    writes = []

    async def write_source(_ref, _path, authored):
        writes.append(authored)

    async def preview_compile(_self, *, final=True):
        assert final is False
        return {"state": "preview_ready", "build_id": "preview-1"}

    monkeypatch.setattr(pdf_generation_runtime, "_write_authored_source", write_source)
    monkeypatch.setattr(pdf_generation._GenerationRun, "_compile", preview_compile)
    generation = pdf_generation._GenerationRun(
        ref={},
        brief=_intent(
            kind="article",
            profile_id="generic_article",
            citation_policy="required",
        ),
        model="model",
        project_path="documents/article",
        scaffold_source=SCAFFOLD,
        draft=DocumentDraft(
            1,
            1,
            "Draft",
            (DraftBlock("body_text", "paragraph", text="Unverified draft"),),
        ),
    )

    result = await generation.execute(execution=object())

    assert result == {
        "state": "draft_ready",
        "build_id": "preview-1",
        "stage": "evidence",
        "failure_code": "evidence_incomplete",
        "project_saved": True,
    }
    assert len(writes) == 1
    assert "Unverified draft" in writes[0].files["content/001-body_text.tex"]


@pytest.mark.asyncio
async def test_visual_repair_cannot_replace_an_unrelated_block(monkeypatch) -> None:
    draft = DocumentDraft(
        1,
        2,
        "Stable",
        (
            DraftBlock("safe_block", "paragraph", text="keep"),
            DraftBlock("bad_block", "paragraph", text="overflow"),
        ),
    )
    arguments = {
        "base_version": 2,
        "replacements": [
            {
                "block_id": "safe_block",
                "kind": "paragraph",
                "title": "",
                "text": "unexpected replacement",
                "items": [],
                "columns": [],
                "rows": [],
                "source_id": 0,
                "asset_path": "",
                "level": 1,
            }
        ],
    }
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            function=SimpleNamespace(
                                name="submit_document_patch", arguments=arguments
                            )
                        )
                    ]
                )
            )
        ]
    )

    async def model_call(*_args, **_kwargs):
        return SimpleNamespace(response=response)

    monkeypatch.setattr(authoring_repair, "invoke_model_call", model_call)
    repaired = await repair_semantic_draft(
        _intent(),
        draft,
        ["layout_overflow:bad_block"],
        "model",
        execution=SimpleNamespace(provider_snapshot=None),
    )

    assert repaired is None


@pytest.mark.asyncio
async def test_source_and_visual_repair_budgets_are_independent(monkeypatch) -> None:
    statuses = iter(
        (
            {"state": "failed", "failure_code": "compile_failed"},
            {"state": "failed", "failure_code": "compile_failed"},
            {"state": "visual_pending", "build_id": "build-3"},
            {"state": "ready", "build_id": "build-4"},
        )
    )
    authored = SimpleNamespace()
    builds = 0

    async def author(_self, *, execution):
        del execution
        return authored

    async def compile_document(_self):
        nonlocal builds
        builds += 1
        return next(statuses)

    async def visual(_self, _status, *, execution):
        del execution
        _self.visual_repairs += 1
        return {
            "state": "failed",
            "failure_code": "visual_audit_failed",
            "diagnostics": [{"code": "layout_overflow", "block_id": "body_text"}],
        }, True

    async def write_source(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pdf_generation._GenerationRun, "_author", author)
    monkeypatch.setattr(pdf_generation._GenerationRun, "_compile", compile_document)
    monkeypatch.setattr(pdf_generation._GenerationRun, "_resolve_visual_audit", visual)
    monkeypatch.setattr(pdf_generation_runtime, "_write_authored_source", write_source)
    generation = pdf_generation._GenerationRun(
        ref={},
        brief=_intent(),
        model="model",
        project_path="documents/report",
        scaffold_source=SCAFFOLD,
        draft=DocumentDraft(
            1,
            1,
            "Draft",
            (DraftBlock("body_text", "paragraph", text="body"),),
        ),
    )

    result = await generation.execute(execution=object())

    assert result is not None
    assert result["state"] == "ready"
    assert result["build_id"] == "build-4"
    assert generation.source_repairs == 2
    assert generation.visual_repairs == 1
    assert builds == 4
