"""Prompt truncation cannot masquerade as complete source-backed authoring."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.documents.authoring import execution as authoring
from service.domain.documents.authoring.checkpoint import DocumentAuthoringCheckpoint
from service.domain.documents.evidence.bundle import build_document_evidence_bundle
from service.domain.documents.intent import deterministic_intent
from service.domain.documents.semantic.draft import DraftBlock
from service.domain.documents.semantic.outline import DocumentOutline, DocumentOutlineSection
from service.domain.subagents import pdf_generation_runtime as runtime
from service.domain.subagents.pdf_generation import PDFGenerationAgent


def _evidence(size):
    return build_document_evidence_bundle(
        [{"name": "large.md", "content": "SOURCE_EVIDENCE " * size}], None
    )


@pytest.mark.asyncio
async def test_oversized_outline_does_not_pay_for_a_silently_incomplete_source_view(monkeypatch):
    call = AsyncMock(return_value=SimpleNamespace(response={}))
    monkeypatch.setattr(authoring, "invoke_model_call", call)
    result = await authoring.author_semantic_draft_result(
        deterministic_intent("Подготовь отчет"),
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=None,
        evidence=_evidence(6000),
    )
    assert result.failure_code == "evidence_incomplete"
    assert result.failure_stage == "outline"
    assert result.repair_used is False
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_selected_section_budget_failure_does_not_invoke_model_or_protocol_repair(
    monkeypatch,
):
    bundle = _evidence(1800)
    section = DocumentOutlineSection(
        "large",
        "Раздел",
        "Полный пересказ",
        ("paragraph",),
        tuple(sorted(bundle.material_source_ids)),
    )
    outline = DocumentOutline("Документ", (section,))
    call = AsyncMock(return_value=SimpleNamespace(response={}))
    monkeypatch.setattr(authoring, "invoke_model_call", call)
    blocks, failure, _ = await authoring._invoke_section_round(
        deterministic_intent("Подготовь отчет"),
        outline,
        section,
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=None,
        evidence=bundle,
        repair=False,
    )
    assert blocks is None and failure == "evidence_incomplete"
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_budget_failure_keeps_accepted_checkpoint_without_regeneration(monkeypatch):
    bundle = _evidence(1800)
    accepted = DocumentOutlineSection("accepted", "Введение", "Обзор", ("paragraph",), ())
    remaining = DocumentOutlineSection(
        "remaining",
        "Основная часть",
        "Полный пересказ",
        ("paragraph",),
        tuple(sorted(bundle.material_source_ids)),
    )
    block = DraftBlock(
        block_id="accepted_001", kind="paragraph", text="Accepted source-backed text."
    )
    checkpoint = DocumentAuthoringCheckpoint(
        "section_authoring",
        DocumentOutline("Документ", (accepted, remaining)),
        (block,),
        ("accepted",),
        False,
    )
    call = AsyncMock(return_value=SimpleNamespace(response={}))
    save = AsyncMock()
    monkeypatch.setattr(authoring, "invoke_model_call", call)
    result = await authoring.author_semantic_draft_result(
        deterministic_intent("Подготовь отчет"),
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=None,
        evidence=bundle,
        resume=checkpoint,
        checkpoint=save,
    )
    assert result.failure_code == "evidence_incomplete"
    assert result.draft.blocks == (block,)
    assert result.accepted_sections == 1 and result.repair_used is False
    assert save.call_args.args[0].accepted_section_ids == ("accepted",)
    call.assert_not_awaited()


def test_precompile_budget_refusal_does_not_claim_a_checked_pdf_or_request_paid_research():
    message = PDFGenerationAgent._failure_message(
        {"state": "failed", "stage": "outline", "failure_code": "evidence_incomplete"}
    )
    assert "бюджет" in message.lower()
    assert "проверен" not in message.lower()
    assert "подтвердите исследование" not in message.lower()


@pytest.mark.parametrize("limit", [0, 100, 256, 9000])
def test_partial_prompt_view_exposes_bounded_omissions_without_raw_source_in_repr(limit):
    bundle = _evidence(900)
    projection = bundle.project_context(max_chars=limit)
    assert projection.complete is False and projection.omitted_blocks > 0
    assert len(projection.context) <= limit
    assert "SOURCE_EVIDENCE" not in repr(projection)
    assert "att-" not in repr(projection)


def test_complete_selected_source_has_no_false_budget_refusal():
    bundle = _evidence(900)
    source_id = bundle.attachments[0].chunks[-1].source_id
    projection = bundle.project_context(max_chars=18_000, source_ids=(source_id,))
    assert projection.complete is True
    assert projection.omitted_blocks == 0 and projection.included_blocks == 1
    assert source_id in projection.context


def test_unknown_requested_source_is_incomplete_without_unrelated_fallback():
    projection = _evidence(900).project_context(source_ids=("unknown-private-target",))
    assert not projection.complete and projection.omitted_blocks == 1
    assert projection.context == "" and projection.included_blocks == 0


def test_preview_bibliography_guidance_is_unchanged_when_compilation_actually_ran():
    message = PDFGenerationAgent._failure_message(
        {"state": "draft_ready", "stage": "evidence", "failure_code": "evidence_incomplete"}
    )
    assert "проверен" in message.lower()
    assert "подтвердите исследование" in message.lower()


@pytest.mark.asyncio
async def test_project_budget_failure_never_compiles_publishes_or_claims_an_artifact(monkeypatch):
    model = AsyncMock(return_value=SimpleNamespace(response={}))
    source = AsyncMock()
    compile = AsyncMock()
    monkeypatch.setattr(authoring, "invoke_model_call", model)
    monkeypatch.setattr(runtime, "_write_authored_source", source)
    monkeypatch.setattr(runtime.DocumentGenerationRun, "_compile", compile)
    run = runtime.DocumentGenerationRun(
        brief=deterministic_intent("Подготовь отчет"),
        model="GigaChat-2",
        ref={},
        project_path="report",
        scaffold_source="\\begin{document}\\end{document}",
        evidence=_evidence(6000),
    )
    status = await run.execute(execution=SimpleNamespace(provider_snapshot=None))
    assert status["state"] == "failed" and status["failure_code"] == "evidence_incomplete"
    assert status["stage"] == "outline" and status["project_saved"] is True
    assert "document_artifacts" not in status and "artifacts" not in status
    assert status["authoring_repair_used"] is False
    model.assert_not_awaited()
    source.assert_not_awaited()
    compile.assert_not_awaited()
