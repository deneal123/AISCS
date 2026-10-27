"""Улучшение нельзя приписать probe, которому не передавали рекомендацию."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.persistence.harness import refinement
from service.shared.harness_protocol import Continuation, HarnessFailure
from tests.test_harness_refinement import probe_grant, scenario


def guidance(attempt):
    return (
        "Рекомендация после неудачной попытки; не расширяет полномочия и не является "
        "подтверждением результата. Исходные правила и обязательные проверки сохраняются.\n"
        + attempt.proposal.instruction
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["missing", "edited", "role"])
async def test_candidate_checkpoint_must_actually_include_its_instruction(monkeypatch, attack):
    current, attempt, baseline, proposed = scenario()
    monkeypatch.setattr(refinement, "_grant", AsyncMock(side_effect=[baseline, proposed]))
    messages = [{"role": "user", "content": guidance(attempt)}]
    if attack == "missing":
        messages = []
    elif attack == "edited":
        messages[0]["content"] = "Другая инструкция"
    else:
        messages[0]["role"] = "assistant"
    new = Continuation.model_validate(
        {
            **current.continuation.model_dump(mode="json"),
            "refinement": attempt,
            "next_step": 1,
            "messages": messages,
        }
    )
    with pytest.raises(HarnessFailure, match="verification_missing"):
        await refinement.require_refinement_transition(None, {}, current, new)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attack",
    [
        "missing",
        "edited",
        "role",
        "estimated",
        "provider",
        "fee",
        "calls",
        "duplicate",
        "unverified",
    ],
)
async def test_only_a_confirmed_model_probe_with_actual_guidance_can_be_adopted(
    monkeypatch, attack
):
    current, attempt, _, _ = scenario()
    current.continuation = current.continuation.model_copy(update={"refinement": attempt})
    current.state.evidence = [object()]
    probe = probe_grant(attempt)
    body = json.loads(probe["request"]["canonical_request"])
    if attack == "missing":
        body["messages"] = []
    elif attack == "edited":
        body["messages"][0]["content"] = "Другая инструкция"
    elif attack == "role":
        body["messages"][0]["role"] = "assistant"
    elif attack == "estimated":
        probe["receipt"]["estimated"] = True
    elif attack == "provider":
        probe["request"]["provider"] = "another"
    elif attack == "fee":
        probe["request"]["billing_tool"] = "workspace_tool"
    elif attack == "calls":
        probe["receipt"]["message"]["tool_calls"] = []
    probe["request"]["canonical_request"] = json.dumps(body)

    class DB:
        async def scalar(self, *_args):
            return True

        async def execute(self, *_args):
            rows = [probe, probe] if attack == "duplicate" else [probe]
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))

    save = AsyncMock()
    monkeypatch.setattr(refinement, "save_checkpoint", save)
    await refinement.adopt_verified_refinement(
        DB(),
        {"task_id": uuid4()},
        current,
        {"status": "completed", "verified": attack != "unverified"},
    )
    save.assert_not_awaited()
