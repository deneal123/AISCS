"""Настоящий общий цикл agents; сетевой предохранитель запрещает платный fallback."""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import UTC, datetime


async def exercise():
    import httpx

    os.environ["AGENTS__LLM_PROVIDER"] = "local"
    os.environ["AGENTS__CHAT_MAX_TOKENS"] = "256"
    logging.disable(logging.CRITICAL)
    original = httpx.AsyncHTTPTransport.handle_async_request
    counters = {"calls": 0, "blocked": 0}
    failed = []

    async def guarded(transport, request):
        if (request.url.host, request.url.port) != ("local-llm", 8080):
            counters["blocked"] += 1
            raise httpx.ConnectError("conversation_probe_network_denied", request=request)
        if request.method == "POST":
            assert request.url.path == "/v1/chat/completions"
            assert json.loads(request.content)["model"] == "qwen2.5-1.5b-instruct"
            counters["calls"] += 1
        return await original(transport, request)

    httpx.AsyncHTTPTransport.handle_async_request = guarded
    from service.domain.client import registry
    from service.domain.client.providers import local
    from service.domain.execution.context import PrivateRunResources, use_run_execution
    from service.domain.pipeline.context.budget import resolve_window
    from service.domain.subagents.general import GeneralAgent
    from service.events import EventType
    from service.schemas.agents import UserContext
    from service.settings import config
    from service.shared.provider_policy_context import use_snapshot

    from service.domain import client

    policy = {
        "disabled": [name for name in registry.PROVIDER_MODULES if name != "local"],
        "blocked": [],
    }
    with use_snapshot(policy):
        await registry.get_provider_model_catalog("local", force_refresh=True)
        for text in ("привет", "оиили", "Сколько будет 2 плюс 3?"):
            before = counters["calls"]
            started = time.monotonic()
            with use_run_execution(PrivateRunResources()) as execution:
                await client.initialize_run_provider_admission(execution)
                agent = GeneralAgent({"model": local.MODEL_ID})
                context = UserContext(user_id="", request_time=datetime.now(UTC))
                events = [event async for event in agent._run_chat_streamed(text, context)]
                final = "".join(
                    str(e.data or "") for e in events if e.type == EventType.STREAM_CHUNK
                )
                tools = [e for e in events if e.type == EventType.TOOL_CALL_START]
                errors = [e for e in events if e.type == EventType.ERROR]
                capped = any((e.metadata or {}).get("tool_cap_reached") for e in events)
                if tools or errors or capped or not final.strip() or counters["calls"] == before:
                    failed.append(text)
                window = await resolve_window(local.MODEL_ID, config)
                print(
                    json.dumps(
                        {
                            "case": text,
                            "seconds": round(time.monotonic() - started, 2),
                            "calls": counters["calls"] - before,
                            "tools": len(tools),
                            "errors": len(errors),
                            "error_codes": [(e.metadata or {}).get("failure_code") for e in errors],
                            "active": client.get_active_provider(),
                            "catalog": list(execution.provider_admission.snapshot.catalogs),
                            "text": final,
                            "window": window,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    await local.get_openai_client().close()
    print(json.dumps(counters), flush=True)
    print(json.dumps({"failed_cases": failed}, ensure_ascii=False), flush=True)
    return bool(failed)


if __name__ == "__main__":
    sys.exit(asyncio.run(exercise()))
