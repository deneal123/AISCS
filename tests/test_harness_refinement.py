"""Рекомендация не подтверждает сама себя и не расширяет интерфейс инструментов."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from service.services.chat.persistence.harness import refinement
from service.shared.harness_protocol import Continuation, HarnessFailure
from service.shared.harness_refinement import RefinementAttempt, render_refinement


def scenario():
    proposal = {"instruction": "Сначала прочитай исходный файл.", "tools": []}
    attempt = RefinementAttempt(
        baseline_operation=str(uuid4()),
        proposal_operation=str(uuid4()),
        proposal=proposal,
        probe_step=1,
        baseline_evidence_count=0,
    )
    current = SimpleNamespace(
        continuation=Continuation(provider={"provider": "local", "model": "test"}, next_step=0),
        state=SimpleNamespace(evidence=[]),
    )
    baseline = {
        "request": {
            "provider": "local",
            "model": "test",
            "kind": "chat",
            "continuation_step": 0,
            "canonical_request": json.dumps({"tools": [{"function": {"name": "ide_read_file"}}]}),
        },
        "receipt": {"finish_reason": "stop", "message": {"content": "Ответ без чтения"}},
    }
    proposed = {
        "request": {"provider": "local", "model": "test", "kind": "meta_usage"},
        "receipt": {"message": {"content": json.dumps(proposal, ensure_ascii=False)}},
    }
    return current, attempt, baseline, proposed


def candidate_continuation(current, attempt):
    return Continuation.model_validate(
        {
            **current.continuation.model_dump(mode="json"),
            "refinement": attempt,
            "next_step": 1,
            "messages": [{"role": "user", "content": render_refinement(attempt.proposal)}],
        }
    )


def probe_grant(attempt):
    return {
        "state": "succeeded",
        "request": {
            "provider": "local",
            "model": "test",
            "kind": "chat",
            "continuation_step": 1,
            "canonical_request": json.dumps(
                {"messages": [{"role": "user", "content": render_refinement(attempt.proposal)}]}
            ),
        },
        "receipt": {
            "finish_reason": "tool_calls",
            "estimated": False,
            "message": {"tool_calls": [{"id": "read-1", "function": {"name": "ide_read_file"}}]},
        },
    }


@pytest.mark.asyncio
async def test_candidate_is_bound_to_actual_model_receipts(monkeypatch):
    current, attempt, baseline, proposed = scenario()
    calls = []

    async def grant(db, row, operation_id):
        calls.append(operation_id)
        return baseline if operation_id == attempt.baseline_operation else proposed

    monkeypatch.setattr(refinement, "_grant", grant)
    new = candidate_continuation(current, attempt)
    await refinement.require_refinement_transition(None, {}, current, new)
    assert calls == [attempt.baseline_operation, attempt.proposal_operation]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attack", ["adopt", "reset", "step", "evidence", "model", "forged", "tool"]
)
async def test_forged_or_expanded_refinement_is_rejected(monkeypatch, attack):
    current, attempt, baseline, proposed = scenario()
    raw = attempt.model_dump(mode="json")
    if attack == "adopt":
        raw["adopted"] = True
    elif attack == "reset":
        current.continuation = current.continuation.model_copy(update={"refinement": attempt})
        raw["proposal"]["instruction"] = "Новая инструкция вместо сохранённой"
    elif attack == "step":
        raw["probe_step"] = 2
    elif attack == "evidence":
        raw["baseline_evidence_count"] = 1
    elif attack == "model":
        proposed["request"]["provider"] = "another"
    elif attack == "forged":
        raw["proposal"]["instruction"] = "Рекомендация без receipt"
    elif attack == "tool":
        raw["proposal"]["tools"] = [{"name": "host_shell", "advice": "Новый инструмент"}]
        proposed["receipt"]["message"]["content"] = json.dumps(raw["proposal"])

    async def grant(db, row, operation_id):
        return baseline if operation_id == attempt.baseline_operation else proposed

    monkeypatch.setattr(refinement, "_grant", grant)
    new = candidate_continuation(current, RefinementAttempt.model_validate(raw))
    with pytest.raises(HarnessFailure):
        await refinement.require_refinement_transition(None, {}, current, new)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "evidence", "probe", "expected"),
    [
        ("partial", True, True, False),
        ("blocked", True, True, False),
        ("completed", False, True, False),
        ("completed", True, False, False),
        ("completed", True, True, True),
    ],
)
async def test_only_verified_improvement_can_be_adopted(
    monkeypatch, status, evidence, probe, expected
):
    current, attempt, _, _ = scenario()
    current.continuation = current.continuation.model_copy(update={"refinement": attempt})
    current.state.evidence = [object()] if evidence else []
    writes = []

    class DB:
        async def execute(self, statement, parameters):
            assert parameters["step"] == "1"
            rows = [probe_grant(attempt)] if probe else []
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))

    async def save(db, row, **values):
        writes.append(values)

    monkeypatch.setattr(refinement, "save_checkpoint", save)
    await refinement.adopt_verified_refinement(
        DB(), {"task_id": uuid4()}, current, {"status": status, "verified": status == "completed"}
    )
    assert bool(writes) is expected
    if expected:
        assert writes[0]["continuation"].refinement.adopted
        assert writes[0]["state"] is current.state
