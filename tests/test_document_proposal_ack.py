"""Потеря ACK предложения не разрешает новый POST или нулевую стоимость."""

import json
from unittest.mock import AsyncMock

import pytest

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.integration_failure import IntegrationFailureCode
from service.domain.runners.harness.tools import execute_harness_tool
from service.domain.runners.tool_runtime.execution import ValidatedToolCall
from service.domain.tools.documents.proposals import save_review_proposal
from service.domain.tools.workspace.client import WorkspaceUnavailable
from service.shared.document_review import review_proposal_id
from service.shared.harness_protocol import EffectResult
from tests.test_harness_reconciliation import Journal


def document_journal():
    journal = Journal(None)
    state = journal.current.state
    contract = {
        **state.contract.model_dump(mode="json"),
        "kind": "document",
        "actions": ["read", "document"],
        "criteria": [{"criterion_id": "slides", "kind": "pdf", "target": "documents/slides"}],
    }
    journal.current = journal.current.model_copy(
        update={
            "admission": journal.current.admission.model_copy(
                update={"surface": "pdf", "actions": ("read", "document")}
            ),
            "state": state.advance(contract=contract),
        }
    )
    return journal


def values():
    target = {"path": "documents/slides", "draft_digest": "a" * 64, "expected_revision": "r1"}
    operations = {"base_version": 1, "replacements": [{"block_id": "intro", "kind": "slide"}]}
    stored = {
        **operations,
        "draft_digest": target["draft_digest"],
        "expected_revision": "r1",
        "selected_block_ids": [],
    }
    proposal_id = review_proposal_id(target["path"], stored)
    return (
        target,
        operations,
        {
            "path": target["path"],
            "proposal_id": proposal_id,
            "proposal": stored,
        },
    )


@pytest.mark.asyncio
async def test_lost_ack_reads_exact_immutable_proposal_without_second_post():
    target, operations, stored = values()
    remote = AsyncMock(side_effect=[WorkspaceUnavailable(IntegrationFailureCode.TIMEOUT), stored])
    with use_run_execution(PrivateRunResources()) as execution:
        result = await save_review_proposal(execution, {}, target, operations, send=remote)
        assert result.succeeded and result.charged and not execution.workspace.unconfirmed
        assert execution.policy.values["document_proposal"] == stored["proposal_id"]
    assert [item.args[1] for item in remote.await_args_list] == [
        "documents/proposals",
        "documents/proposals/read",
    ]
    assert remote.await_args_list[1].args[2] == {"proposal_id": stored["proposal_id"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["missing", "path", "proposal", "id"])
async def test_unconfirmed_or_mismatched_read_remains_unknown_and_holds_fee(mismatch):
    target, operations, stored = values()
    if mismatch == "missing":
        recovered = WorkspaceUnavailable(IntegrationFailureCode.UNAVAILABLE)
    else:
        recovered = dict(stored)
        field = {"path": "path", "proposal": "proposal", "id": "proposal_id"}[mismatch]
        recovered[field] = "untrusted"
    remote = AsyncMock(
        side_effect=[WorkspaceUnavailable(IntegrationFailureCode.TRANSPORT), recovered]
    )
    journal = document_journal()
    client = journal.client()
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = client
        execution.bind_task_state(journal.current.state)
        call = ValidatedToolCall(0, "p1", "tex_propose_patch", {}, "{}", "{}", "key")
        result = await execute_harness_tool(
            call, lambda: save_review_proposal(execution, {}, target, operations, send=remote)
        )
        assert not result.succeeded and execution.workspace.unconfirmed
        assert not execution.task_state.evidence
        assert client.failure == "operation_unknown"
        assert not execution.policy.values.get("document_proposal")
    effect, fee = [
        next(item for item in journal.operations.values() if item["operation_kind"] == kind)
        for kind in ("effect", "paid")
    ]
    assert effect["status"] == fee["status"] == "unknown"
    assert EffectResult.model_validate(effect["receipt"]).charged is None
    assert remote.await_count == 2


@pytest.mark.asyncio
async def test_cached_receipt_restores_review_reference_without_adapter_or_extra_fee():
    target, operations, stored = values()
    journal = document_journal()
    with use_run_execution(PrivateRunResources()) as first:
        first.harness = journal.client()
        first.bind_task_state(journal.current.state)
        call = ValidatedToolCall(0, "p1", "tex_propose_structure", {}, "{}", "{}", "key")
        await execute_harness_tool(
            call,
            lambda: save_review_proposal(
                first,
                {},
                target,
                operations,
                send=AsyncMock(return_value={"proposal_id": stored["proposal_id"]}),
            ),
        )
    with use_run_execution(PrivateRunResources()) as restored:
        restored.harness = journal.client()
        restored.bind_task_state(journal.current.state)
        invoke = AsyncMock()
        result = await execute_harness_tool(call, invoke)
        assert result.succeeded and not result.charged
        assert restored.policy.values["document_proposal"] == stored["proposal_id"]
        assert not restored.task_state.evidence
        invoke.assert_not_awaited()
    assert journal.counts["dispatch_effect"] == journal.counts["grant"] == 1


@pytest.mark.asyncio
async def test_explicit_rejection_is_nonbillable_and_does_not_probe_again():
    target, operations, _ = values()
    remote = AsyncMock(side_effect=WorkspaceUnavailable(IntegrationFailureCode.CONFLICT))
    with use_run_execution(PrivateRunResources()) as execution:
        result = await save_review_proposal(execution, {}, target, operations, send=remote)
        assert not result.succeeded and not result.charged and not execution.workspace.unconfirmed
    remote.assert_awaited_once()


@pytest.mark.asyncio
async def test_reused_stored_proposal_is_not_charged_again():
    target, operations, stored = values()
    with use_run_execution(PrivateRunResources()) as execution:
        result = await save_review_proposal(
            execution,
            {},
            target,
            operations,
            send=AsyncMock(return_value={"proposal_id": stored["proposal_id"], "reused": True}),
        )
        assert result.succeeded and result.reused and not result.charged
        assert json.loads(result.text)["proposal_id"] == stored["proposal_id"]
