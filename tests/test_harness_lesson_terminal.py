"""Транспортный SUCCESS не позволяет учиться на частично выполненной задаче."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from service.services.chat.persistence.harness.lessons import read_lessons
from service.shared.harness_refinement import RefinementAttempt
from service.shared.task_contract import CompletionVerifier
from tests.test_task_contract import evidence, state


def scenario():
    task = state(evidence=[evidence(), evidence("test")])
    result = CompletionVerifier.evaluate(task)
    attempt = RefinementAttempt(
        baseline_operation=str(uuid4()),
        proposal_operation=str(uuid4()),
        proposal={"instruction": "Прочитай исходники до ответа.", "tools": []},
        probe_step=1,
        baseline_evidence_count=0,
        adopted=True,
    )
    current = SimpleNamespace(
        continuation=SimpleNamespace(provider=SimpleNamespace(provider="local", model="test")),
        state=task,
        admission=SimpleNamespace(
            project_id="project", generation="g1", surface="ide", goal="Цель"
        ),
    )
    row = {"user_id": uuid4(), "task_id": uuid4()}
    saved = {"refinement": attempt.model_dump(mode="json"), "task_result": result}
    return current, row, saved


class DB:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""

    async def execute(self, statement, parameters):
        self.query = str(statement)
        return SimpleNamespace(mappings=lambda: self.rows)


@pytest.mark.asyncio
async def test_only_final_verified_completed_result_makes_a_lesson_reusable():
    current, row, saved = scenario()
    assert await read_lessons(DB([saved]), row, current) == [saved["refinement"]["proposal"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["partial", "blocked", "waiting_user", "cancelled"])
async def test_preliminary_adoption_cannot_survive_a_non_completed_final_result(status):
    current, row, saved = scenario()
    saved["task_result"].update(
        status=status,
        verified=False,
        blocker="cancelled" if status == "cancelled" else "verification_failed",
    )
    assert await read_lessons(DB([saved]), row, current) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["missing", "v1", "unverified", "references", "schema_string"])
async def test_incomplete_or_inconsistent_terminal_proof_is_not_a_lesson(attack):
    current, row, saved = scenario()
    if attack == "missing":
        saved.pop("task_result")
    elif attack == "v1":
        saved["task_result"] = {"schema_version": 1, "status": "completed"}
    elif attack == "unverified":
        saved["task_result"]["verified"] = False
    elif attack == "references":
        saved["task_result"]["references"] = []
    else:
        saved["task_result"]["schema_version"] = "2"
    assert await read_lessons(DB([saved]), row, current) == []
