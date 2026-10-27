"""Реальная CPU-модель через backend/agents/workspace; не scripted модель и не worker."""

import asyncio
import json
import logging
import sys
import traceback

import httpx
from sqlalchemy import text

from scripts.harness.live.command import admit, prepare
from scripts.harness.live.environment import backend_http, environment

STAGE = "environment"
MODEL = "qwen2.5-1.5b-instruct"
QUESTION = (
    "Создай в корне проекта hello_world.py. Скрипт должен вывести ровно hello world "
    "и перевод строки. Сохрани и прочитай файл, затем запусти его для проверки "
    "ожидаемого вывода. Не устанавливай зависимости. Заверши только после успешной проверки."
)


async def exercise(container):
    global STAGE
    from service.composition.ide import build_ide_runtime
    from service.infrastructure.agents_client.http_agent_engine import HttpAgentEngine
    from service.services.chat.application.harness_capability import issue
    from service.services.chat.application.ide.agent_context import build_ide_run_ref
    from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
    from service.settings import config
    from service.shared.harness_protocol import Exchange

    STAGE = "prepare_project"
    scope, generation = await prepare(container, create_file=False)
    owner = await admit(container, scope, generation, credits=100000, model=MODEL, goal=QUESTION)
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
    STAGE = "execute_local_model"
    async with asyncio.timeout(560):
        result = await HttpAgentEngine(config).execute(
            text=QUESTION,
            thread_id=str(scope.thread_id),
            user_id=str(scope.user_id),
            selected_model=MODEL,
            route_override="general",
            memory_enabled=False,
            planning=False,
            multi_intent=False,
            workspace_ref=reference,
            provider_policy={
                "disabled": ["gigachat", "openai", "routerai", "openrouter", "mws"],
                "blocked": [],
            },
        )
    task = result.get("metadata", {}).get("task_result") or {}
    async with httpx.AsyncClient(
        timeout=5, headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key}
    ) as client:
        observed = (await client.get("http://agents:8091/__harness_acceptance__/transport")).json()
    if task.get("status") != "completed":
        print(
            json.dumps(
                {
                    "stage": STAGE,
                    "task_status": task.get("status"),
                    "blocker": task.get("blocker"),
                    "unchecked": task.get("unchecked"),
                    "transport": observed,
                }
            ),
            flush=True,
        )
    assert task.get("status") == "completed" and task["verified"] and not task["unchecked"]
    STAGE = "independent_evidence"
    state = (
        await HarnessRuntimeRepository(container.infra.pg_connector).exchange(
            owner, Exchange(opcode="state")
        )
    )["snapshot"]
    assert state["continuation"]["provider"]["provider"] == "local"
    assert state["held_credits"] == 0 and 0 < state["state"]["rounds"] <= 16
    resolved = await runtime.resolve(scope)
    actual = await runtime.client.read(
        scope.user_id, resolved.binding, operation="file", path="hello_world.py"
    )
    assert "hello world" in actual["content"]
    async with container.infra.pg_connector.get_session_context() as db:
        commands = (
            (
                await db.execute(
                    text(
                        "SELECT command FROM profile.harness_operation "
                        "WHERE task_id=:task AND command IS NOT NULL ORDER BY created_at"
                    ),
                    {"task": owner.params()["task_id"]},
                )
            )
            .scalars()
            .all()
        )
    assert commands
    command = commands[-1]
    assert command["cleanup_confirmed"] and command["verification"]["status"] == "passed"
    assert command["result"]["stdout"] == "hello world\n"
    assert command["snapshot_id"] and command["final_revision"] == state["state"]["source_revision"]
    return {
        "local_model_ide_verified": True,
        "rounds": task["rounds"],
        "provider_calls": observed["completions"],
        "commands": len(commands),
        "worker_covered": False,
    }


async def main():
    logging.disable(logging.CRITICAL)
    async with environment() as container, backend_http(container):
        result = await exercise(container)
    print(json.dumps({**result, "fixture_data_removed": True}), flush=True)


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
            ),
            flush=True,
        )
        sys.exit(1)
