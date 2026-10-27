"""Outer transport recovery must project the run ledger without usage events."""

import asyncio
import json

import pytest

from service.application.reply_assembler import ReplyAssembler
from service.domain.execution.context import (
    PrivateRunResources,
    current_execution,
    observe_run_usage,
    use_run_execution,
)
from service.domain.usage.ledger import UsageLedger, UsageReceipt
from service.events import AgentEvent, EventType
from service.presentation.routers.agent import run as run_module
from service.schemas.run import AgentRunInput


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "internal"])
async def test_outer_failure_preserves_receipt_without_any_usage_event(monkeypatch, failure):
    class Engine:
        async def execute(self, **kwargs):
            with use_run_execution(PrivateRunResources()) as execution:
                execution.usage.record(UsageReceipt("call", "openai", "synthetic", 2, 1))
                if failure == "internal":
                    raise RuntimeError("private-provider-body-marker")
                await asyncio.Event().wait()

    monkeypatch.setattr(run_module, "internal_auth", lambda value: None)
    monkeypatch.setattr(run_module.runtime, "DefaultAgentExecutionService", Engine)
    monkeypatch.setattr(run_module, "_run_deadline_sec", lambda: 0.01)
    monkeypatch.setattr(run_module, "_HARD_STOP_GRACE_SEC", 0)
    response = await run_module.run(
        AgentRunInput(text="synthetic", thread_id="thread", selected_model="synthetic"),
        authorization=None,
        correlation_id="synthetic",
    )
    lines = [json.loads(line) async for line in response.body_iterator]
    terminals = [line["__result__"] for line in lines if "__result__" in line]
    assert len(terminals) == 1
    result = terminals[0]
    assert result["prompt_tokens"] == 2 and result["completion_tokens"] == 1
    assert result["total_tokens"] == 3
    assert result["per_call_usage"] == [
        {"model": "synthetic", "provider": "openai", "prompt": 2, "completion": 1}
    ]
    assert "private-provider-body-marker" not in json.dumps(lines)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "internal"])
@pytest.mark.parametrize(
    "provider,model,reason",
    [
        (None, "synthetic", "missing_provider"),
        ("openai", None, "missing_model"),
    ],
)
async def test_interrupted_receipt_provenance_anomaly_survives_terminal(
    monkeypatch, failure, provider, model, reason
):
    class Engine:
        async def execute(self, **kwargs):
            with use_run_execution(PrivateRunResources()) as execution:
                execution.usage.record(UsageReceipt("accepted", provider, model, 2, 1))
                if failure == "internal":
                    raise RuntimeError("PRIVATE_PROVIDER_BODY")
                await asyncio.Event().wait()

    monkeypatch.setattr(run_module, "internal_auth", lambda value: None)
    monkeypatch.setattr(run_module.runtime, "DefaultAgentExecutionService", Engine)
    monkeypatch.setattr(run_module, "_run_deadline_sec", lambda: 0.01)
    monkeypatch.setattr(run_module, "_HARD_STOP_GRACE_SEC", 0)
    response = await run_module.run(
        AgentRunInput(text="synthetic", thread_id="thread", selected_model="requested"),
        authorization=None,
        correlation_id="synthetic",
    )
    lines = [json.loads(line) async for line in response.body_iterator]
    results = [line["__result__"] for line in lines if "__result__" in line]
    assert len(results) == 1
    result = results[0]
    assert result["total_tokens"] == 3
    assert len(result["per_call_usage"]) == 1
    assert result["per_call_usage"][0]["model"] == model
    assert result["per_call_usage"][0].get("provider") == provider
    assert result["metadata"]["usage_integrity"] == {
        "anomaly_count": 1,
        "reason_codes": [reason],
    }
    assert "PRIVATE_PROVIDER_BODY" not in json.dumps(lines)


def test_recovery_ignores_usage_integrity_not_owned_by_ledger():
    from types import SimpleNamespace

    from service.presentation.routers.agent.run_recovery import build_timeout_result

    ledger = UsageLedger()
    ledger.record(UsageReceipt("accepted", "openai", "synthetic", 2, 1))
    recovery = ReplyAssembler(ledger)
    spoofed = {"anomaly_count": 99, "reason_codes": ["PRIVATE_ANOMALY"]}
    recovery.metadata["usage_integrity"] = spoofed
    incoming = {"usage_integrity": spoofed}
    for _ in range(2):
        result = build_timeout_result(
            recovery, incoming, SimpleNamespace(selected_model="requested")
        )
        assert result["total_tokens"] == 3
        assert "usage_integrity" not in result["metadata"]
    assert len(ledger.receipts) == 1
    assert incoming["usage_integrity"] == spoofed


def test_normal_finalization_drops_foreign_usage_integrity():
    from service.application.use_cases.agent_execution_use_cases import PostprocessAgentReplyUseCase

    ledger = UsageLedger()
    ledger.record(UsageReceipt("accepted", "openai", "synthetic", 2, 1))
    assembler = ReplyAssembler(ledger)
    assembler.reply_parts.append("accepted answer")
    assembler.finalize_usage()
    _reply, metadata = PostprocessAgentReplyUseCase().execute(
        reply_assembler=assembler,
        metadata={"usage_integrity": {"reason_codes": ["PRIVATE_ANOMALY"]}},
    )
    assert "usage_integrity" not in metadata


@pytest.mark.asyncio
async def test_concurrent_failure_recovery_keeps_run_ledgers_separate(monkeypatch):
    class Engine:
        async def execute(self, **kwargs):
            with use_run_execution(PrivateRunResources()) as execution:
                amount = 2 if kwargs["thread_id"] == "one" else 7
                receipt = UsageReceipt("call", "openai", "synthetic", amount, 1, estimated=True)
                execution.usage.record(receipt)
                execution.usage.record(receipt)
                # Event replay must not become another billing source.
                for _ in range(2):
                    kwargs["on_event"](
                        AgentEvent(
                            type=EventType.AGENT_COMPLETE,
                            agent_name="general",
                            metadata={
                                "token_usage": {
                                    "model": "synthetic",
                                    "prompt": 900,
                                    "completion": 900,
                                }
                            },
                        )
                    )
                await asyncio.sleep(0)
                raise RuntimeError("private-concurrent-marker")

    monkeypatch.setattr(run_module, "internal_auth", lambda value: None)
    monkeypatch.setattr(run_module.runtime, "DefaultAgentExecutionService", Engine)

    async def collect(thread):
        response = await run_module.run(
            AgentRunInput(text="synthetic", thread_id=thread),
            authorization=None,
            correlation_id="synthetic",
        )
        records = [json.loads(line) async for line in response.body_iterator]
        return [line["__result__"] for line in records if "__result__" in line][0]

    results = await asyncio.gather(collect("one"), collect("two"))
    assert [result["total_tokens"] for result in results] == [3, 8]
    assert all(len(result["per_call_usage"]) == 1 for result in results)
    assert all(result["per_call_usage"][0]["estimated"] for result in results)


@pytest.mark.asyncio
async def test_error_before_any_accepted_receipt_retains_nonbillable_error_path(monkeypatch):
    class Engine:
        async def execute(self, **kwargs):
            with use_run_execution(PrivateRunResources()):
                raise RuntimeError("private-unaccepted-marker")

    monkeypatch.setattr(run_module, "internal_auth", lambda value: None)
    monkeypatch.setattr(run_module.runtime, "DefaultAgentExecutionService", Engine)
    response = await run_module.run(
        AgentRunInput(text="synthetic", thread_id="thread"),
        authorization=None,
        correlation_id="synthetic",
    )
    records = [json.loads(line) async for line in response.body_iterator]
    assert records == [{"__error__": "internal"}]


def test_transport_observer_is_scoped_and_does_not_own_private_resources():
    parent_execution = current_execution()
    observed = []
    with observe_run_usage(observed.append):
        with use_run_execution(PrivateRunResources()) as execution:
            assert observed == [execution.usage]
    assert current_execution() is parent_execution
    with use_run_execution(PrivateRunResources()):
        assert len(observed) == 1


def test_recovery_assembler_rejects_another_run_ledger():
    assembler = ReplyAssembler()
    ledger = UsageLedger()
    assembler.bind_usage_ledger(ledger)
    assembler.bind_usage_ledger(ledger)
    with pytest.raises(RuntimeError, match="Run usage ownership unavailable"):
        assembler.bind_usage_ledger(UsageLedger())
