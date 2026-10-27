"""Unowned compiler conditions cannot trigger a global paid content rewrite."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.documents.authoring import repair as authoring_repair
from service.domain.documents.intent import deterministic_intent
from service.domain.documents.repair_provenance import scoped_source_diagnostics
from service.domain.documents.semantic.draft import DocumentDraft, DraftBlock
from service.domain.subagents import pdf_generation_runtime as runtime


def _draft():
    return DocumentDraft(1, 1, "Report", (DraftBlock("safe_block", "paragraph", text="Keep"),))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "diagnostics",
    [
        ["compile_failed"],
        ["undefined_control_sequence"],
        ["undefined_control_sequence:safe_block", "missing_file"],
        ["undefined_control_sequence:safe_block"] * 21,
    ],
)
async def test_unowned_or_over_budget_diagnostics_refuse_before_model_call(
    monkeypatch, diagnostics
):
    invoke = AsyncMock(return_value=SimpleNamespace(response=SimpleNamespace(choices=[])))
    monkeypatch.setattr(authoring_repair, "invoke_model_call", invoke)
    result = await authoring_repair.repair_semantic_draft(
        deterministic_intent("Prepare a report"),
        _draft(),
        diagnostics,
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
    )
    assert result is None
    invoke.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["compile_failed", "build_timeout", "source_changed"])
async def test_unowned_failed_build_does_not_rebuild_or_consume_repair_budget(monkeypatch, failure):
    run = runtime.DocumentGenerationRun(
        ref={},
        brief=deterministic_intent("Prepare a report"),
        model="GigaChat-2",
        project_path="report",
        scaffold_source="",
        draft=_draft(),
    )
    author = AsyncMock(return_value=object())
    compile_document = AsyncMock(return_value={"state": "failed", "failure_code": failure})
    monkeypatch.setattr(runtime.DocumentGenerationRun, "_author", author)
    monkeypatch.setattr(runtime.DocumentGenerationRun, "_compile", compile_document)
    monkeypatch.setattr(runtime, "_write_authored_source", AsyncMock())
    result = await run.execute(execution=object())
    assert result["failure_code"] == failure and result["project_saved"] is True
    assert author.await_count == 1 and compile_document.await_count == 1
    assert run.source_repairs == 0


def _status(diagnostics, *, failure="compile_failed"):
    return {"state": "failed", "failure_code": failure, "diagnostics": diagnostics}


def test_scoped_compiler_error_ignores_nonfatal_aggregate_warning():
    status = _status(
        [
            {"severity": "warning", "code": "overfull_box"},
            {"severity": "error", "code": "missing_math_delimiter", "block_id": "safe_block"},
            {"severity": "error", "code": "missing_math_delimiter", "block_id": "safe_block"},
        ]
    )
    assert scoped_source_diagnostics(status, _draft()) == ("missing_math_delimiter:safe_block",)


@pytest.mark.parametrize(
    "issue",
    [
        {"severity": "error", "code": "missing_file"},
        {"severity": "error", "code": "undefined_control_sequence", "block_id": "unknown_block"},
        {"severity": "error", "code": "PRIVATE_EXCEPTION", "block_id": "safe_block"},
        {"severity": "error", "code": "page_size", "block_id": "safe_block"},
        {"severity": [], "code": "missing_file", "block_id": "safe_block"},
        {"severity": "fatal", "code": "missing_file", "block_id": "safe_block"},
        "PRIVATE_PAYLOAD",
    ],
)
def test_one_unowned_or_nonsemantic_fatal_condition_prevents_partial_admission(issue):
    valid = {"severity": "error", "code": "missing_math_delimiter", "block_id": "safe_block"}
    assert scoped_source_diagnostics(_status([valid, issue]), _draft()) is None


@pytest.mark.parametrize(
    "failure",
    [
        "source_changed",
        "build_timeout",
        "build_cancelled",
        "build_interrupted",
        "internal",
    ],
)
def test_nonrepairable_failure_cannot_be_overruled_by_located_diagnostic(failure):
    valid = {"severity": "error", "code": "missing_math_delimiter", "block_id": "safe_block"}
    assert scoped_source_diagnostics(_status([valid], failure=failure), _draft()) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"failure_code": []},
        {"failure_code": {"private": "payload"}},
        {"diagnostics": None},
        {"diagnostics": {}},
        {"diagnostics": []},
        {"diagnostics": [{"severity": "warning", "code": "overfull_box"}]},
    ],
)
def test_malformed_or_warning_only_status_cannot_trigger_repair(changes):
    valid = {"severity": "error", "code": "missing_math_delimiter", "block_id": "safe_block"}
    assert scoped_source_diagnostics({**_status([valid]), **changes}, _draft()) is None


@pytest.mark.asyncio
async def test_literal_text_never_consumes_source_repair_or_calls_authoring_model(monkeypatch):
    from dataclasses import replace

    run = runtime.DocumentGenerationRun(
        ref={},
        brief=replace(deterministic_intent("Prepare a report"), literal_text="тест"),
        model="GigaChat-2",
        project_path="report",
        scaffold_source="",
        draft=_draft(),
    )
    author = AsyncMock(return_value=object())
    compile_document = AsyncMock(
        return_value=_status(
            [{"severity": "error", "code": "missing_math_delimiter", "block_id": "safe_block"}]
        )
    )
    monkeypatch.setattr(runtime.DocumentGenerationRun, "_author", author)
    monkeypatch.setattr(runtime.DocumentGenerationRun, "_compile", compile_document)
    monkeypatch.setattr(runtime, "_write_authored_source", AsyncMock())
    result = await run.execute(execution=object())
    assert result["failure_code"] == "compile_failed"
    assert author.await_count == 1 and compile_document.await_count == 1
    assert run.source_repairs == 0


@pytest.mark.asyncio
async def test_owned_source_error_still_repairs_without_replacing_unaffected_blocks(monkeypatch):
    import json

    target = DraftBlock("repair_block", "paragraph", text="Before")
    safe = DraftBlock("safe_block", "paragraph", text="Keep")
    draft = DocumentDraft(1, 1, "Report", (target, safe))
    function = SimpleNamespace(
        name="submit_document_patch",
        arguments={
            "base_version": 1,
            "replacements": [
                {"block_id": "repair_block", "kind": "paragraph", "text": "Corrected"}
            ],
        },
    )
    invoke = AsyncMock(
        return_value=SimpleNamespace(
            response=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(tool_calls=[SimpleNamespace(function=function)])
                    )
                ]
            )
        )
    )
    monkeypatch.setattr(authoring_repair, "invoke_model_call", invoke)
    result = await authoring_repair.repair_semantic_draft(
        deterministic_intent("Prepare a report"),
        draft,
        ["missing_math_delimiter:repair_block"],
        "GigaChat-2",
        execution=SimpleNamespace(provider_snapshot=None),
    )
    assert result is not None and result.blocks[0].text == "Corrected"
    assert result.blocks[1] is safe and result.version == draft.version + 1
    prompt = json.loads(invoke.call_args.kwargs["messages"][1]["content"])
    assert [block["block_id"] for block in prompt["draft"]["blocks"]] == ["repair_block"]
    assert invoke.await_count == 1
