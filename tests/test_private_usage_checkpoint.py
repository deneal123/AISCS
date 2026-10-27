"""Private checkpoint is canonical accounting, not trace token_usage or prompt data."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.usage.ledger import UsageLedger, UsageReceipt
from service.events import AgentEvent, EventType
from service.presentation.routers.agent import run as run_module
from service.presentation.routers.agent.usage_checkpoint import checkpoint_observer
from service.schemas.run import AgentRunInput


def test_observer_emits_only_canonical_changes_and_unsubscribes():
    ledger = UsageLedger()
    emitted = []
    attempt = str(uuid4())
    unsubscribe = ledger.subscribe(
        checkpoint_observer(attempt, lambda k, v: emitted.append((k, v)))
    )
    estimate = UsageReceipt("call", "openai", "synthetic", 2, 1, estimated=True)
    ledger.record(estimate)
    ledger.record(estimate)
    ledger.record(replace(estimate, prompt=3, estimated=False))
    assert [value["revision"] for _, value in emitted] == [1, 2]
    assert all(len(value["receipts"]) == 1 for _, value in emitted)
    assert emitted[-1][1]["receipts"][0]["prompt"] == 3
    unsubscribe()
    unsubscribe()
    ledger.record(UsageReceipt("other", "openai", "synthetic", 2, 1))
    assert len(emitted) == 2


@pytest.mark.asyncio
async def test_private_run_frame_ignores_trace_usage_and_does_not_leak_resources(monkeypatch):
    class Engine:
        async def execute(self, **kwargs):
            with use_run_execution(
                PrivateRunResources(workspace_ref={"token": "PRIVATE_MARKER"})
            ) as execution:
                execution.usage.record(UsageReceipt("call", "openai", "synthetic", 2, 1))
                kwargs["on_event"](
                    AgentEvent(
                        type=EventType.AGENT_COMPLETE,
                        metadata={"token_usage": {"prompt": 999, "completion": 999}},
                    )
                )
                raise RuntimeError("PRIVATE_MARKER")

    monkeypatch.setattr(run_module, "internal_auth", lambda _v: None)
    monkeypatch.setattr(run_module.runtime, "DefaultAgentExecutionService", Engine)
    attempt = str(uuid4())
    response = await run_module.run(
        AgentRunInput(text="PRIVATE_MARKER", thread_id="synthetic"),
        authorization=None,
        correlation_id=None,
        execution_attempt=attempt,
    )
    frames = [json.loads(line) async for line in response.body_iterator]
    private = [frame["__usage_checkpoint__"] for frame in frames if "__usage_checkpoint__" in frame]
    assert len(private) == 1 and private[0]["attempt_id"] == attempt
    assert private[0]["receipts"][0]["prompt"] == 2
    assert "PRIVATE_MARKER" not in json.dumps(private)
    terminals = [frame["__result__"] for frame in frames if "__result__" in frame]
    assert len(terminals) == 1 and terminals[0]["total_tokens"] == 3
