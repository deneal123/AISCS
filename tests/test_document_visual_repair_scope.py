"""Page provenance scopes visual repair without inventing a culprit block."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.documents import visual_audit
from service.domain.documents.intent import deterministic_intent
from service.domain.documents.repair_provenance import page_provenance, scoped_visual_diagnostics
from service.domain.documents.semantic.draft import DocumentDraft, DraftBlock
from service.domain.subagents import pdf_generation_runtime as runtime


async def _resolve(monkeypatch, pages):
    run = runtime.DocumentGenerationRun(
        ref={},
        brief=deterministic_intent("Prepare a report"),
        model="GigaChat-2",
        project_path="document",
        scaffold_source="",
        draft=DocumentDraft(
            1,
            1,
            "Report",
            tuple(
                DraftBlock(name, "paragraph")
                for name in ("first_block", "second_block", "other_page")
            ),
        ),
    )
    audit = SimpleNamespace(
        passed=False,
        retryable=False,
        status="failed",
        diagnostics=({"code": "visual_clipping", "page": 1},),
        block_pages=pages,
    )
    monkeypatch.setattr(runtime, "audit_document_build", AsyncMock(return_value=audit))
    monkeypatch.setattr(
        runtime,
        "call",
        AsyncMock(return_value={"state": "failed", "failure_code": "visual_audit_failed"}),
    )
    status, may_repair = await run._resolve_visual_audit(
        {"state": "visual_pending", "build_id": "opaque-build"},
        execution=object(),
    )
    return run, status, may_repair


@pytest.mark.asyncio
async def test_multiple_blocks_on_failed_page_do_not_trigger_whole_document_repair(monkeypatch):
    run, status, may_repair = await _resolve(
        monkeypatch, ((1, ("first_block", "second_block")), (2, ("other_page",)))
    )
    assert may_repair and run.visual_repairs == 1
    assert run.visual_diagnostics == ("visual_clipping:first_block", "visual_clipping:second_block")
    assert "visual_diagnostics" not in status
    assert "other_page" not in repr(run.visual_diagnostics)


@pytest.mark.asyncio
@pytest.mark.parametrize("pages", [(), ((2, ("other_page",)),), ((1, ("unknown_block",)),)])
async def test_unbound_page_does_not_authorize_global_visual_repair(monkeypatch, pages):
    run, status, may_repair = await _resolve(monkeypatch, pages)
    assert not may_repair and run.visual_repairs == 0
    assert status["failure_code"] == "visual_audit_failed"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [{"page": True, "block_ids": ["first_block"]}],
        [{"page": 3, "block_ids": ["first_block"]}],
        [{"page": 1, "block_ids": ["first_block", "first_block"]}],
        [{"page": 1, "block_ids": ["../private"]}],
        [{"page": 1, "block_ids": ["first_block"]}] * 2,
    ],
)
def test_ambiguous_page_inventory_fails_closed(raw):
    assert page_provenance(raw, 2) == ()


def test_repair_targets_are_bounded_not_silently_truncated():
    blocks = tuple(DraftBlock(f"block_{index}", "paragraph") for index in range(21))
    draft = DocumentDraft(1, 1, "Report", blocks)
    pages = ((1, tuple(block.block_id for block in blocks)),)
    assert (
        scoped_visual_diagnostics(
            ({"code": "visual_clipping", "page": 1},), pages, draft, visual_audit.VISUAL_CODES
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("reported_state", ["failed", "ready"])
async def test_failed_audit_carries_claimed_provenance_privately(monkeypatch, reported_state):
    monkeypatch.setattr(visual_audit, "require_execution", lambda value: value)
    monkeypatch.setattr(
        visual_audit, "list_qualified_models", AsyncMock(return_value=["GigaChat-2-Max"])
    )
    monkeypatch.setattr(visual_audit, "pick_text_model", lambda models: models[0])
    monkeypatch.setattr(
        visual_audit,
        "call",
        AsyncMock(
            return_value={
                "audit": {
                    "page_count": 1,
                    "source_digest": "a" * 64,
                    "artifact_sha256": "b" * 64,
                    "block_pages": [{"page": 1, "block_ids": ["first_block", "second_block"]}],
                }
            }
        ),
    )
    monkeypatch.setattr(visual_audit, "download_binary", AsyncMock(return_value=(b"fake-png", {})))
    monkeypatch.setattr(visual_audit, "_reconcile_blank_diagnostics", lambda issues, images: issues)
    function = SimpleNamespace(
        name="submit_visual_audit",
        arguments={"passed": False, "issues": [{"code": "visual_clipping", "page": 1}]},
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(tool_calls=[SimpleNamespace(function=function)])
            )
        ]
    )
    monkeypatch.setattr(
        visual_audit,
        "invoke_model_call",
        AsyncMock(return_value=SimpleNamespace(response=response)),
    )
    monkeypatch.setattr(visual_audit, "_report", AsyncMock(return_value={"state": reported_state}))
    result = await visual_audit.audit_document_build(
        {}, "opaque-build", execution=SimpleNamespace(provider_snapshot=None)
    )
    assert not result.passed and not result.retryable
    assert result.block_pages == ((1, ("first_block", "second_block")),)
    assert "first_block" not in repr(result)


@pytest.mark.asyncio
async def test_private_page_bindings_do_not_enter_audit_http_response(monkeypatch):
    from service.presentation.routers.capabilities import document_audit as endpoint

    monkeypatch.setattr(endpoint, "internal_auth", lambda value: None)
    result = visual_audit.VisualAuditResult(
        "failed",
        False,
        False,
        ({"code": "visual_clipping", "page": 1},),
        ((1, ("private_first_block", "private_second_block")),),
    )
    monkeypatch.setattr(endpoint, "audit_document_build", AsyncMock(return_value=result))
    response = await endpoint.audit_document(
        endpoint.DocumentAuditRequest(build_id="opaque-build", workspace_ref={}),
        authorization="private",
    )
    assert set(response) == {"status", "passed", "retryable", "diagnostic_count", "usage"}
    assert "private_first_block" not in repr(response)
