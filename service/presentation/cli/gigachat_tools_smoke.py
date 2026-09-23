"""Opt-in live GigaChat function validation and two-round smoke.

The command uses synthetic input only and never prints provider response bodies,
function schemas, arguments, state identifiers, credentials, or generated content.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from service.domain.capabilities.runtime import get_static_catalog
from service.domain.client import stream_chat_completion
from service.domain.client.providers import gigachat
from service.domain.client.providers.gigachat_schema import prepare_gigachat_functions
from service.domain.client.registry import initialize_run_provider_admission
from service.domain.run_context import PrivateRunResources, use_run_execution
from service.domain.runners.chat_provider_round import provider_events
from service.domain.runners.support import _tools_to_openai
from service.presentation.cli.gigachat_smoke_support import (
    bounded_failure_code,
    require_tool_model,
)

_MODEL = os.getenv("GIGACHAT_SMOKE_MODEL", "GigaChat-2").strip() or "GigaChat-2"


def _validation_counts(payload: Any) -> tuple[int, int]:
    if not isinstance(payload, dict):
        return 1, 0
    errors = payload.get("errors") or []
    warnings = payload.get("warnings") or []
    error_count = len(errors) if isinstance(errors, list) else 1
    warning_count = len(warnings) if isinstance(warnings, list) else 0
    return error_count, warning_count


async def _validate(functions: list[dict]) -> None:
    base_url = gigachat._RUNTIME.resolve_base_url()  # noqa: SLF001 - operational adapter check
    async with gigachat._make_http_client() as client:  # noqa: SLF001
        for function in functions:
            response = await client.post(f"{base_url}/functions/validate", json=function)
            if response.status_code != 200:
                raise RuntimeError(f"validation_http_{response.status_code}")
            errors, warnings = _validation_counts(response.json())
            print(f"validate {function['name']}: errors={errors} warnings={warnings}")
            if errors:
                raise RuntimeError("validation_failed")


async def _two_round_smoke() -> None:
    tool = {
        "type": "function",
        "function": {
            "name": "synthetic_lookup",
            "description": "Return a deterministic synthetic value.",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string", "description": "Synthetic lookup key."}},
                "required": ["key"],
                "additionalProperties": False,
            },
        },
    }
    messages: list[dict] = [
        {
            "role": "user",
            "content": "Call synthetic_lookup exactly once with key smoke.",
        }
    ]
    with use_run_execution(PrivateRunResources()) as execution:
        await initialize_run_provider_admission(execution)
        session = execution.provider_session
        first_events = [
            event
            async for event in provider_events(
                stream_chat_completion,
                messages=messages,
                model=_MODEL,
                max_tokens=64,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": "synthetic_lookup"}},
                pin_provider="gigachat",
                provider_session=session,
            )
        ]
        calls = [call for event in first_events for call in event.tool_calls]
        if len(calls) != 1 or calls[0].get("name") != "synthetic_lookup":
            raise RuntimeError("function_call_missing")
        if session.private_state("gigachat") is None:
            raise RuntimeError("provider_state_missing")
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": calls[0]["id"],
                            "type": "function",
                            "function": {
                                "name": calls[0]["name"],
                                "arguments": calls[0]["arguments"],
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": calls[0]["id"],
                    "content": "synthetic-ok",
                },
            ]
        )
        _ = [
            event
            async for event in provider_events(
                stream_chat_completion,
                messages=messages,
                model=_MODEL,
                max_tokens=32,
                tools=[tool],
                tool_choice="none",
                pin_provider="gigachat",
                provider_session=session,
            )
        ]
        if session.pinned_provider != "gigachat":
            raise RuntimeError("provider_not_pinned")
        prompt = session.usage.prompt_tokens
        completion = session.usage.completion_tokens
        total = session.usage.total_tokens
    print(
        f"two-round: provider=gigachat model={_MODEL} calls=2 "
        f"prompt={prompt} completion={completion} total={total}"
    )


async def run_tools_certification() -> None:
    if gigachat.get_openai_client() is None:
        raise RuntimeError(gigachat.configuration_error() or "provider_not_configured")
    await require_tool_model(_MODEL)
    static_tools = [spec.tool for spec in get_static_catalog().native_tools.values()]
    functions = prepare_gigachat_functions(
        [item["function"] for item in _tools_to_openai(static_tools)],
        fill_missing_descriptions=False,
    )
    await _validate(functions)
    await _two_round_smoke()


async def _main() -> None:
    await run_tools_certification()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except Exception as exc:  # noqa: BLE001 - CLI must keep diagnostics bounded
        print(f"gigachat tools smoke: FAILED code={bounded_failure_code(exc)}")
        raise SystemExit(1) from None
    print("gigachat tools smoke: OK")
