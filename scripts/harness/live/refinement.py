"""Независимая проверка принятого улучшения по committed журналу и исходному intent."""

from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

from sqlalchemy import text

QUESTION = (
    "Создай файл hello_world.py в рабочем каталоге. Используй инструменты проекта, "
    "сохрани и прочитай файл, затем запусти скрипт и проверь ровно hello world с переводом строки. "
    "Не устанавливай зависимости."
)


async def assert_adopted(container, job, *, terminal=False):
    async with container.infra.pg_connector.get_session_context() as db:
        row = (
            (
                await db.execute(
                    text(
                        "SELECT user_id,admission,continuation,checkpoint "
                        "FROM profile.harness_task WHERE task_id=:task"
                    ),
                    {"task": UUID(str(job))},
                )
            )
            .mappings()
            .one()
        )
        grants = (
            (
                await db.execute(
                    text(
                        "SELECT operation_id,request,receipt,state FROM profile.harness_grant "
                        "WHERE task_id=:task"
                    ),
                    {"task": UUID(str(job))},
                )
            )
            .mappings()
            .all()
        )
    candidate = row["continuation"]["refinement"]
    assert candidate["adopted"] is True
    assert row["checkpoint"]["state"]["protocol_repairs"] == 1
    operations = {str(grant["operation_id"]): grant for grant in grants}
    baseline = operations[candidate["baseline_operation"]]
    proposal = operations[candidate["proposal_operation"]]
    assert baseline["receipt"]["finish_reason"] == "stop"
    assert not baseline["receipt"]["message"]["tool_calls"]
    assert proposal["state"] == "succeeded" and proposal["request"]["kind"] == "meta_usage"
    assert candidate["proposal_operation"] == str(
        uuid5(UUID(str(job)), "provider-purpose:instruction_refinement")
    )
    probes = [
        grant
        for grant in grants
        if grant["request"].get("continuation_step") == candidate["probe_step"]
    ]
    assert len(probes) == 1 and probes[0]["state"] == "succeeded"
    assert probes[0]["receipt"]["message"]["tool_calls"]
    assert len(row["checkpoint"]["state"]["evidence"]) > candidate["baseline_evidence_count"]
    model_grants = [grant for grant in grants if not grant["request"].get("billing_tool")]
    assert all(grant["state"] == "succeeded" for grant in model_grants)
    if terminal:
        await assert_reusable_lesson(container, row, candidate["proposal"])
    return {"model_calls": len(model_grants)}


async def assert_reusable_lesson(container, row, proposal):
    from service.services.chat.persistence.harness.lessons import read_lessons
    from service.shared.harness_protocol import Admission, Continuation
    from service.shared.task_contract import TaskState

    current = SimpleNamespace(
        admission=Admission.model_validate(row["admission"]),
        continuation=Continuation.model_validate(row["continuation"]),
        state=TaskState.model_validate(row["checkpoint"]["state"]),
    )
    # Только чтение результата настоящего worker. UUID другого задания задаёт
    # scope запроса следующего использования, не создаёт job или новые полномочия.
    async with container.infra.pg_connector.get_session_context() as db:
        lessons = await read_lessons(db, {"user_id": row["user_id"], "task_id": uuid4()}, current)
    assert lessons == [proposal]
