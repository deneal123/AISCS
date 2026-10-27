"""Only backend-confirmed criteria may bypass the model call after an IDE report."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.harness.completion import verified_ide_report
from service.shared.task_contract import TaskContract, TaskEvidence, TaskState


def verified_state():
    contract = TaskContract(
        task_id=str(uuid4()),
        project_id="project",
        generation="generation",
        kind="change",
        goal="create and check",
        actions=["read", "write", "exec"],
        criteria=[
            {"criterion_id": "script", "kind": "file", "target": "hello_world.py"},
            {"criterion_id": "verify_project", "kind": "command"},
        ],
        credit_limit=1000,
    )
    return TaskState(
        contract=contract,
        source_revision="r1",
        rounds=9,
        repairs=1,
        evidence=[
            TaskEvidence(
                criterion_id=criterion.criterion_id,
                operation_id=str(uuid4()),
                kind=criterion.kind,
                target=criterion.target,
                source_revision="r1",
                digest="a" * 64,
                outcome="passed",
                exit_code=0 if criterion.kind == "command" else None,
            )
            for criterion in contract.criteria
        ],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("blocker", [None, "verification_missing", "cost_unknown", "cancelled"])
async def test_report_requires_backend_confirmation_even_with_locally_verified_evidence(blocker):
    with use_run_execution(PrivateRunResources()) as execution:
        execution.task_state = verified_state()
        execution.workspace.ide_summary = "Создано и проверено."
        projection = execution.completion_verifier.evaluate(execution.task_state)
        if blocker:
            projection.update(
                status="cancelled" if blocker == "cancelled" else "blocked",
                blocker=blocker,
                verified=False,
            )
        execution.harness = SimpleNamespace(
            failure="", exchange=AsyncMock(return_value={"result": projection})
        )
        state = SimpleNamespace(execution=execution, collected="", model="test")
        event = await verified_ide_report(
            state, [{"name": "ide_finish_task"}], agent_name="general"
        )
        assert bool(event) == (blocker is None)
        assert state.collected == ("Создано и проверено." if blocker is None else "")
        execution.harness.exchange.assert_awaited_once_with(opcode="result")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "guard", ["unverified", "stale", "cancelled", "unknown", "failed", "not_finish", "no_report"]
)
async def test_summary_does_not_close_unverified_stale_or_failed_work(guard):
    with use_run_execution(PrivateRunResources()) as execution:
        execution.task_state = verified_state()
        execution.workspace.ide_summary = "Неподтверждённое заявление."
        execution.harness = SimpleNamespace(failure="", exchange=AsyncMock())
        if guard == "unverified":
            execution.task_state = execution.task_state.advance(evidence=[])
        if guard == "stale":
            execution.task_state = execution.task_state.advance(source_revision="r2")
        if guard == "cancelled":
            execution.cancel()
        if guard == "unknown":
            execution.workspace.ide_unconfirmed = True
        if guard == "failed":
            execution.harness.failure = "checkpoint_unavailable"
        if guard == "no_report":
            execution.workspace.ide_summary = None
        calls = [{"name": "ide_read_file" if guard == "not_finish" else "ide_finish_task"}]
        state = SimpleNamespace(execution=execution, collected="", model="test")
        assert await verified_ide_report(state, calls, agent_name="general") is None
        execution.harness.exchange.assert_not_awaited()
        assert state.collected == ""
