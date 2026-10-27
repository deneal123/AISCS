"""Real common loop and IDE effects; only provider HTTP is scripted in agents."""

import asyncio
import json
import logging
import os
import sys
import traceback

import httpx
from sqlalchemy import text

from scripts.harness.live.command import admit, prepare
from scripts.harness.live.environment import backend_http, environment

logging.disable(logging.CRITICAL)
STAGE = "environment"


async def exercise(container):
    global STAGE
    from service.composition.ide import build_ide_runtime
    from service.infrastructure.agents_client.http_agent_engine import HttpAgentEngine
    from service.services.chat.application.harness_capability import issue
    from service.services.chat.application.ide.agent_context import build_ide_run_ref
    from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
    from service.settings import config
    from service.shared.harness_protocol import Exchange

    provider = os.environ.get("HARNESS_ACCEPTANCE_PROVIDER", "gigachat")
    model = {
        "gigachat": "GigaChat-3-Lightning",
        "routerai": "openai/gpt-4o-mini",
        "openai": "gpt-4o-mini",
    }[provider]
    repair = os.environ.get("HARNESS_ACCEPTANCE_SCENARIO", "hello") == "repair"
    refine = os.environ.get("HARNESS_ACCEPTANCE_SCENARIO") == "refine"
    finish = os.environ.get("HARNESS_ACCEPTANCE_SCENARIO") == "finish"
    long = os.environ.get("HARNESS_ACCEPTANCE_SCENARIO") == "long"
    from scripts.harness.live import long_run
    from scripts.harness.live.refinement import QUESTION, assert_adopted

    question = (
        QUESTION if refine else "Create hello_world.py and verify that it prints hello world."
    )
    if finish:
        question = (
            "Создай hello_world.py. Он должен вывести ровно hello world и перевод строки. "
            "Сохрани и прочитай его, выполни проверку запуска без установки зависимостей."
        )
    if long:
        question = long_run.QUESTION
    STAGE = "prepare_empty_project"
    scope, generation = await prepare(container, create_file=False)
    STAGE = "admit_task"
    owner = await admit(
        container,
        scope,
        generation,
        credits=100000,
        model=model,
        goal=question if refine or finish or long else None,
    )
    runtime = build_ide_runtime(container.infra.pg_connector)
    reference = await build_ide_run_ref(
        runtime,
        container.infra.redis_client,
        thread_id=str(scope.thread_id),
        user_id=str(scope.user_id),
        raw={"repository_id": str(scope.repository_id), "generation": generation},
        run_id=owner.job_id,
    )
    reference["harness_ref"] = {"task_id": owner.task_id, "capability": issue(owner)}
    events = []
    STAGE = "execute_agents"
    async with asyncio.timeout(300 if long else 130):
        result = await HttpAgentEngine(config).execute(
            text=question,
            thread_id=str(scope.thread_id),
            user_id=str(scope.user_id),
            selected_model=model,
            route_override="general",
            memory_enabled=False,
            planning=False,
            multi_intent=False,
            workspace_ref=reference,
            provider_policy={
                "disabled": [
                    name
                    for name in ("gigachat", "openai", "routerai", "openrouter", "mws")
                    if name != provider
                ],
                "blocked": [],
            },
            on_event=lambda event: events.append(event.model_dump(mode="json")),
        )
    STAGE = "verify_task_result"
    task = result.get("metadata", {}).get("task_result")
    if task is None or task["status"] != "completed":
        # Closed diagnostics, never a reply, prompt, tool result, token or internal ID.
        print(
            json.dumps(
                {
                    "stage": STAGE,
                    "status": task.get("status") if task else None,
                    "blocker": task.get("blocker") if task else None,
                    "execution_status": result.get("metadata", {}).get("execution_status"),
                }
            ),
            flush=True,
        )
    assert task and task["status"] == "completed" and task["verified"]
    if repair:
        assert any(
            message["role"] == "user"
            and str(message.get("content", "")).startswith("[harness:verification-repair:")
            for message in (
                await HarnessRuntimeRepository(container.infra.pg_connector).exchange(
                    owner, Exchange(opcode="state")
                )
            )["snapshot"]["continuation"]["messages"]
        )
    assert not task["unchecked"] and task["rounds"] >= 5
    assert set(task["confirmed"]) == (long_run.CRITERIA if long else {"script", "verify_project"})
    if long:
        assert task["rounds"] == 16
    current = await HarnessRuntimeRepository(container.infra.pg_connector).exchange(
        owner, Exchange(opcode="state")
    )
    state = current["snapshot"]
    if finish:
        assert state["state"]["protocol_repairs"] == 1
        assert result["metadata"]["ide_summary"] == "Скрипт создан и проверен запуском."
    adaptation = await assert_adopted(container, owner.task_id) if refine else None
    assert state["state"]["rounds"] == task["rounds"]
    assert state["state"]["repairs"] == int(repair)
    assert state["continuation"]["provider"]["provider"] == provider
    assert state["spent_credits"] > 0 and state["held_credits"] == 0
    resolved = await runtime.resolve(scope)
    actual = await runtime.client.read(
        scope.user_id, resolved.binding, operation="file", path="hello_world.py"
    )
    if long:
        await long_run.verify_sources(runtime, scope, resolved.binding, actual["content"])
    else:
        assert actual["content"] == "print('hello world')\n"
    STAGE = "verify_private_receipts"
    async with container.infra.pg_connector.get_session_context() as db:
        model_calls = await db.scalar(
            text(
                "SELECT count(*) FROM profile.harness_grant WHERE task_id=:task "
                "AND request->>'billing_tool' IS NULL AND state='succeeded'"
            ),
            {"task": owner.params()["task_id"]},
        )
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT command FROM profile.harness_operation WHERE command IS NOT NULL "
                        "ORDER BY created_at,operation_id"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == (2 if repair else 1)
        if repair:
            first = rows[0]
            assert first["cleanup_confirmed"] and first["verification"]["status"] == "failed"
            assert first["result"]["stdout"] == "wrong output\n"
            assert first["final_revision"] != rows[-1]["final_revision"]
            assert (
                first["verification"]["recipe_digest"] == rows[-1]["verification"]["recipe_digest"]
            )
            assert first["spec"]["timeout_sec"] != rows[-1]["spec"]["timeout_sec"]
        command = rows[-1]
        assert command["cleanup_confirmed"] and command["verification"]["status"] == "passed"
        assert command["result"]["stdout"] == "hello world\n"
        assert (
            command["snapshot_id"]
            and command["final_revision"] == state["state"]["source_revision"]
        )
    public = json.dumps({"events": events, "result": result})
    if repair:
        assert "НЕПОДТВЕРЖДЁННЫЙ УСПЕХ" not in json.dumps(
            {"events": events, "result": result}, ensure_ascii=False
        )
    for private in (
        reference["token"],
        reference["coordination_capability"],
        reference["harness_ref"]["capability"],
        "ACCEPTANCE_PRIVATE_PROVIDER_STATE",
        "[harness:verification-repair:",
        command["engine_id"],
        command["container_id"],
    ):
        assert private not in public
    async with httpx.AsyncClient(
        timeout=5, headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key}
    ) as client:
        observed = (await client.get("http://agents:8091/__harness_acceptance__/transport")).json()
    assert observed["blocked_requests"] == 0
    if provider == "gigachat":
        assert observed["oauth"] >= 1
    expected_tools = [
        "ide_list_files",
        "ide_write_file",
        "ide_read_file",
        "ide_run_command",
    ]
    if repair:
        expected_tools.extend(
            ["ide_read_file", "ide_edit_file", "ide_read_file", "ide_run_command"]
        )
    expected_tools.append("ide_finish_task")
    if long:
        expected_tools = long_run.TOOLS
    assert observed["tool_names"] == expected_tools
    assert observed["completions"] == model_calls
    if adaptation:
        assert adaptation["model_calls"] == model_calls
    return {
        "agents_harness_verified": True,
        "rounds": task["rounds"],
        "provider_calls": observed["completions"],
        "worker_covered": False,
        "repair_verified": repair,
        "provider": provider,
        **({"instruction_refinement_verified": True} if refine else {}),
        **({"terminal_report_repair_verified": True} if finish else {}),
        **({"sixteen_rounds_verified": True} if long else {}),
    }


async def main():
    async with environment() as container, backend_http(container):
        result = await exercise(container)
    print(json.dumps({**result, "fixture_data_removed": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException as error:
        print(
            json.dumps(
                {
                    "stage": STAGE,
                    "error": type(error).__name__,
                    "frames": [
                        {"function": frame.name, "line": frame.lineno}
                        for frame in traceback.extract_tb(error.__traceback__)[-4:]
                    ],
                }
            )
        )
        sys.exit(1)
