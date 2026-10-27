"""Real private HTTP → console → snapshot storage → workspace/Engine acceptance.

This first probe intentionally does not claim agents/worker completion: its file
is fixture setup, and a file criterion must stay unchecked without an agent receipt.
"""

import asyncio
import json
import logging
import os
import re
import sys
import traceback
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.environment import backend_http, environment

logging.disable(logging.CRITICAL)
STAGE = "environment"


async def prepare(
    container,
    *,
    create_file=True,
    initial_credits=100000,
    topup_credits=0,
    content="print('hello world')\n",
):
    assert type(initial_credits) is int and 0 < initial_credits <= 1_000_000_000
    assert type(topup_credits) is int and 0 <= topup_credits <= 1_000_000_000
    from service.composition.ide import build_ide_runtime
    from service.models.db.db_models import User
    from service.services.chat.application.ide.edits import IdeEditService
    from service.services.chat.application.ide.prepare import IdePrepareService
    from service.services.chat.domain.ide.runtime import RepositoryScope, generation_tag
    from service.services.chat.persistence.chat_repository import ChatRepository

    connector, redis = container.infra.pg_connector, container.infra.redis_client
    actor, thread = uuid4(), uuid4()
    async with connector.get_session_context() as db:
        db.add(
            User(
                id=actor,
                email=f"harness-{actor}@example.test",
                password_hash="!disabled",
                available_launches=initial_credits,
                email_verified=True,
            )
        )
        if topup_credits:
            # The legacy User ORM does not map the migration-owned billing wallet.
            # This is initial provisioning of a new fixture, never a dev-user top-up.
            await db.flush()
            await db.execute(
                text('UPDATE profile."user" SET topup_credit_balance=:credits WHERE id=:actor'),
                {"credits": topup_credits, "actor": actor},
            )
        await db.commit()
    await ChatRepository(connector).create_thread(actor, "Harness acceptance", str(thread))
    runtime = build_ide_runtime(connector)
    prepared = await IdePrepareService(runtime, redis).prepare(
        thread_id=thread,
        user_id=actor,
        session="harness-acceptance-session",
    )
    scope = RepositoryScope(thread, actor, UUID(prepared["repository"]["repository_id"]))
    async with asyncio.timeout(30):
        while prepared["runtime"]["workspace"]["state"] != "ready":
            await asyncio.sleep(0.1)
            prepared["runtime"] = await runtime.status(scope)
    resolved = await runtime.resolve(scope)
    generation = generation_tag(resolved.attempt)
    if not create_file:
        return scope, generation
    edits = IdeEditService(runtime, redis)
    lease = await edits.lease(
        scope,
        path="hello_world.py",
        generation=generation,
        session="harness-acceptance-session",
        action="acquire",
        fence=None,
    )
    await edits.write(
        scope,
        path="hello_world.py",
        generation=generation,
        session="harness-acceptance-session",
        fence=lease["fence"],
        operation="file",
        content=content,
        expected_digest=None,
    )
    await edits.lease(
        scope,
        path="hello_world.py",
        generation=generation,
        session="harness-acceptance-session",
        action="release",
        fence=lease["fence"],
    )
    return scope, generation


async def admit(
    container, scope, generation, *, credits=10000, model=None, goal=None, pdf_context=None
):
    from service.services.billing.application.frozen_pricing import freeze_pricing
    from service.services.billing.application.pricing_service import PricingService
    from service.services.billing.persistence.pricing_repository import PricingRepository
    from service.services.chat.application.harness_capability import HarnessOwner
    from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
    from service.settings import config
    from service.shared.harness_protocol import Admission

    job, attempt, reservation = uuid4(), uuid4(), uuid4()
    owner = HarnessOwner(
        task_id=str(job),
        job_id=str(job),
        user_id=str(scope.user_id),
        thread_id=str(scope.thread_id),
        attempt_id=str(attempt),
        epoch=1,
        project_id=pdf_context["project_id"] if pdf_context else str(scope.repository_id),
        generation=generation,
    )
    admission = Admission(
        task_id=str(job),
        project_id=owner.project_id,
        generation=generation,
        surface="pdf" if pdf_context else "ide",
        goal=goal or "Create and verify hello_world.py",
        source_revision=pdf_context["expected_revision"] if pdf_context else generation,
        actions=["read", "document"] if pdf_context else ["read", "write", "exec"],
        credit_limit=credits,
        reservation_id=str(reservation),
        pricing_model=model,
    )
    connector = container.infra.pg_connector
    async with connector.get_session_context() as db:
        await db.execute(
            text(
                "INSERT INTO profile.user_launch(id,user_id,type,status,payload) "
                "VALUES (:id,:actor,'CHAT','PROCESSING',CAST(:payload AS jsonb))"
            ),
            {
                "id": job,
                "actor": scope.user_id,
                "payload": json.dumps(
                    {
                        "thread_id": str(scope.thread_id),
                        "_execution_attempt_v1": str(attempt),
                        "_execution_accounting_v1": {"reservation_id": str(reservation)},
                    }
                ),
            },
        )
        await db.execute(
            text(
                "INSERT INTO profile.token_reservations "
                "(reservation_id,user_id,tokens_reserved,expires_at,status) "
                "VALUES (:id,:actor,:credits,now()+interval '1 hour','reserved')"
            ),
            {"id": reservation, "actor": scope.user_id, "credits": credits},
        )
        await db.commit()
    tariff = await freeze_pricing(PricingService(PricingRepository(connector), config.billing))
    await HarnessRuntimeRepository(connector).admit(
        owner, admission, tariff, **({"document_context": pdf_context} if pdf_context else {})
    )
    return owner


async def exercise(container):
    global STAGE
    from service.services.chat.application.harness_capability import issue

    STAGE = "prepare_project"
    scope, generation = await prepare(container)
    STAGE = "admit_task"
    owner = await admit(container, scope, generation)
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8002",
        timeout=60,
        headers={"Authorization": "Bearer " + issue(owner)},
    ) as client:

        async def exchange(body):
            from service.shared.harness_protocol import HarnessFailure

            response = await client.post("/internal/harness/v1/exchange", json=body)
            if response.status_code != 200:
                code = response.json().get("detail", {}).get("code", "checkpoint_unavailable")
                raise HarnessFailure(code)
            assert response.headers["cache-control"] == "private, no-store"
            return response.json()

        await exchange(
            {
                "opcode": "seal",
                "expected_revision": 0,
                "proposal": {
                    "kind": "change",
                    "criteria": [
                        {"criterion_id": "script", "kind": "file", "target": "hello_world.py"}
                    ],
                },
            }
        )
        operation = str(uuid4())
        spec = {
            "profile": "python_script",
            "target": "hello_world.py",
            "expected_stdout": "hello world\n",
            "timeout_sec": 10,
            "criterion_id": "verify_project",
        }
        STAGE = "prepare_command"
        await exchange(
            {
                "opcode": "prepare_effect",
                "effect": {
                    "operation_id": operation,
                    "name": "ide_run_command",
                    "action": "exec",
                    "arguments": json.dumps(spec),
                    "source_revision": generation,
                },
            }
        )
        await exchange({"opcode": "dispatch_effect", "operation_id": operation})
        STAGE = "run_command"
        response = await client.post(
            "/internal/harness/v1/commands",
            json={"action": "run", "operation_id": operation, "spec": spec},
        )
        assert response.status_code == 200, "command_refused"
        result = response.json()
        async with asyncio.timeout(40):
            while result["command"]["state"] not in ("completed", "failed", "cancelled"):
                await asyncio.sleep(0.1)
                response = await client.post(
                    "/internal/harness/v1/commands",
                    json={"action": "status", "operation_id": operation},
                )
                assert response.status_code == 200
                result = response.json()
        STAGE = "assert_verified_receipt"
        command = result["command"]
        assert command["state"] == "completed"
        assert command["verification"]["status"] == "passed"
        assert command["result"]["stdout"] == "hello world\n"
        assert command["final_revision"]
        STAGE = "assert_once_only_replay"
        replay = await client.post(
            "/internal/harness/v1/commands",
            json={"action": "run", "operation_id": operation, "spec": spec},
        )
        assert replay.status_code == 200
        assert replay.json()["command"] == command
        completion = (await exchange({"opcode": "result"}))["result"]
        # A fixture-created file is not an agent write receipt, even after a
        # successful check. Do not turn component acceptance into fake completion.
        assert completion["status"] != "completed"
        assert "script" in completion["unchecked"]
        if os.environ.get("HARNESS_ACCEPTANCE_WORKSPACE_FAULT"):
            await assert_dispatch_ack_boundary()
        return {
            "command_verified": True,
            "http_replay_stable": True,
            "agents_worker_covered": False,
        }


async def assert_dispatch_ack_boundary():
    from service.settings import config

    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(
            "http://workspace:8082/__harness_acceptance__/workspace",
            headers={"Authorization": "Bearer " + config.agents.workspace_api_key},
        )
        assert response.status_code == 200
        assert response.json() == {
            "lost": 1,
            "attempts": {"create": 1, "handshake": 1, "dispatch": 1},
            "operations": 1,
        }


async def main():
    async with environment() as container, backend_http(container):
        result = await exercise(container)
    print(json.dumps({**result, "fixture_data_removed": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException as error:
        # No SQL, arguments, credentials, capabilities or command output.
        print(
            json.dumps(
                {
                    "stage": STAGE,
                    "error": type(error).__name__,
                    "code": getattr(error, "code", None)
                    if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", str(getattr(error, "code", "")))
                    else None,
                    "frames": [
                        {"function": frame.name, "line": frame.lineno}
                        for frame in traceback.extract_tb(error.__traceback__)[-4:]
                    ],
                }
            )
        )
        sys.exit(1)
