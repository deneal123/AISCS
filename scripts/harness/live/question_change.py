"""Чтение → вопрос → правка UI → outbox child → новое чтение, без повторного эффекта."""

import asyncio
import hashlib
import json
import os
import sys
from uuid import uuid4

from scripts.harness.live.crash import wait_terminal
from scripts.harness.live.environment import backend_http, environment
from scripts.harness.live.provider_profile import isolate_read_change
from scripts.harness.live.question import answer, transport_status
from scripts.harness.live.question_assertions import job_row
from scripts.harness.live.question_change_facts import facts
from scripts.harness.live.read_change import CONTENT, MODELS, write_as_user
from scripts.harness.live.worker_assertions import read_balance
from scripts.harness.live.worker_process import deliver, prefork_worker
from scripts.harness.live.worker_setup import funded_job
from service.shared.task_contract import CompletionVerifier

QUESTION = (
    "Прочитай hello_world.py, затем спроси, какой файл разобрать подробнее. "
    "После моего ответа прочитай выбранный файл ещё раз. Ничего не меняй и не запускай."
)
STAGE = "environment"


async def exercise(container):
    global STAGE
    from service.composition.ide import build_ide_runtime
    from service.settings import config

    scope, root, balance, kwargs = await funded_job(
        container,
        question=QUESTION,
        create_file=True,
        selected_model=MODELS[os.environ["HARNESS_ACCEPTANCE_PROVIDER"]],
    )
    queue = "harness-" + uuid4().hex
    STAGE = "read_then_park"
    async with prefork_worker(config.pg.db, queue) as (app, first_pid):
        await deliver(app, queue, kwargs)
        paused, original = await facts(container, scope, root)
        parent = await job_row(container, root)
        metadata = parent["payload"]["metadata"]
        assert parent["status"] == "SUCCESS" and metadata["task_result"]["status"] == "waiting_user"
        question = metadata["human_question"]
        assert question["state"] == "pending" and question["resume_job_id"] is None
        assert paused["task"]["continuation"]["phase"] == "waiting_user"
        assert CompletionVerifier.evaluate(original)["confirmed"] == ["source"]
        assert len(paused["operations"]) == len(original.evidence) == 1
        assert original.rounds == 2 and len(paused["charges"]) == 1
        observed = await transport_status()
        await deliver(app, queue, kwargs)
        assert await facts(container, scope, root) == (paused, original)
        assert await transport_status() == observed
    STAGE = "user_edit_while_parked"
    await write_as_user(scope, kwargs["session_data"]["_ide_context"]["generation"])
    changed, stale = await facts(container, scope, root)
    assert stale.source_revision != original.source_revision
    assert CompletionVerifier.evaluate(stale)["unchecked"] == ["source"]
    assert stale.contract == original.contract and stale.evidence == original.evidence
    assert stale.rounds == original.rounds and stale.repairs == original.repairs
    assert changed["grants"] == paused["grants"] and changed["charges"] == paused["charges"]
    assert changed["operations"] == paused["operations"]
    # Вопрос остаётся тем же: новая версия не создаёт новый исходный запрос.
    STAGE = "answer_and_outbox"
    child = await answer(container, scope, root, question, kwargs)
    pending = await job_row(container, child)
    assert pending["status"] == "NEW" and not pending["payload"].get("_execution_attempt_v1")
    child_kwargs = {
        "job_id": str(child),
        "thread_id": str(scope.thread_id),
        "user_id": str(scope.user_id),
        "text": "",
        "session_data": {"_human_question_resume_job_v1": str(child)},
    }
    STAGE = "child_reread"
    async with prefork_worker(config.pg.db, queue, additional_queues=("agents", "maintenance")) as (
        app,
        child_pid,
    ):
        assert child_pid != first_pid
        await wait_terminal(container, child)
        complete, final = await facts(container, scope, root, child)
        terminal = await job_row(container, child)
        result = terminal["payload"]["metadata"]["task_result"]
        assert terminal["status"] == "SUCCESS" and result["status"] == "completed"
        assert result["verified"] and result["confirmed"] == ["source"] and not result["unchecked"]
        assert (
            final.contract == original.contract and final.source_revision == stale.source_revision
        )
        assert final.rounds == original.rounds + 2 and final.repairs == original.repairs
        assert final.protocol_repairs == original.protocol_repairs
        assert final.budget.active_ms >= original.budget.active_ms
        assert complete["task"]["active_job_id"] == child and complete["task"]["fencing_epoch"] > 1
        for key in ("provider", "model"):
            assert (
                complete["task"]["continuation"]["provider"][key]
                == paused["task"]["continuation"]["provider"][key]
            )
        STAGE = "versioned_read_receipts"
        # Checkpoint хранит последнюю проверку критерия; история остаётся в receipt.
        assert len(final.evidence) == 1 and final.evidence != original.evidence
        assert final.evidence[-1].digest == hashlib.sha256(CONTENT.encode()).hexdigest()
        assert final.evidence[-1].source_revision == stale.source_revision
        assert len(complete["operations"]) == 2
        assert all(
            row["intent"]["name"] == "ide_read_file" and row["status"] == "succeeded"
            for row in complete["operations"]
        )
        operations_by_id = {row["operation_id"]: row for row in complete["operations"]}
        assert all(operations_by_id[row["operation_id"]] == row for row in paused["operations"])
        STAGE = "usage_and_settlement"
        grants_by_id = {row["operation_id"]: row for row in complete["grants"]}
        assert all(grants_by_id[row["operation_id"]] == row for row in paused["grants"])
        assert all(row["state"] in {"succeeded", "waived"} for row in complete["grants"])
        assert len(complete["charges"]) == 2
        assert balance - await read_balance(container, scope) == complete["task"]["settled_credits"]
        observed = await transport_status()
        STAGE = "child_redelivery"
        await deliver(app, queue, child_kwargs)
        assert await facts(container, scope, root, child) == (complete, final)
        assert await transport_status() == observed
    STAGE = "child_worker_restart"
    async with prefork_worker(config.pg.db, queue) as (app, restarted_pid):
        assert restarted_pid != child_pid
        await deliver(app, queue, child_kwargs)
        assert await facts(container, scope, root, child) == (complete, final)
        assert await transport_status() == observed
    runtime = build_ide_runtime(container.infra.pg_connector)
    resolved = await runtime.resolve(scope)
    actual = await runtime.client.read(
        scope.user_id, resolved.binding, operation="file", path="hello_world.py"
    )
    assert actual["content"] == CONTENT
    return {
        "parked_read_invalidated": True,
        "child_reread_verified": True,
        "same_task_criteria_counters": True,
        "user_edit_preserved": True,
        "charges": 2,
        "mutations": 0,
        "commands": 0,
        "replay_and_restart_unchanged": True,
    }


async def main():
    isolate_read_change()
    async with environment() as container, backend_http(container):
        result = await exercise(container)
    print(json.dumps({**result, "fixture_data_removed": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException as error:
        print(json.dumps({"stage": STAGE, "error": type(error).__name__}))
        sys.exit(1)
