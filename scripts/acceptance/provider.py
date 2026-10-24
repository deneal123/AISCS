"""Проба настоящего registry/admission/SDK, запускаемая в отдельном agents-процессе."""

import asyncio
import json
import os
import sys


async def exercise(key):
    # До импорта registry: чужие serving процессы и runtime overrides не меняются.
    os.environ["AGENTS__LOCAL_API_KEY"] = key
    os.environ["AGENTS__LOCAL_BASE_URL"] = "http://local-llm:8080/v1"
    from service.domain.client import registry
    from service.domain.client.models.requirements import ModelRequirement
    from service.domain.client.providers import local

    from service.domain import client

    catalog = await registry.get_provider_model_catalog("local", force_refresh=True)
    decision = await registry.qualify_model(
        "local",
        requirement=ModelRequirement(tools=True),
        catalog=catalog,
    )
    assert decision.model == local.MODEL_ID and decision.compatible, "qualification_failed"
    vision = await registry.qualify_model(
        "local",
        requirement=ModelRequirement(vision=True),
        catalog=catalog,
    )
    assert not vision.compatible, "vision_was_invented"
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_number",
                "description": "Прочитать неизвестное число.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
    ]
    response = await client.create_chat_completion(
        messages=[{"role": "user", "content": "Вызови read_number."}],
        model=local.MODEL_ID,
        provider="local",
        pin_provider="local",
        max_tokens=128,
        tools=tools,
        tool_choice="required",
    )
    call = response.choices[0].message.tool_calls[0]
    assert call.function.name == "read_number" and json.loads(call.function.arguments) == {}, (
        "sdk_tool_invalid"
    )
    assert response.usage.total_tokens > 0, "sdk_usage_missing"
    streamed = await local.create_chat_completion(
        messages=[{"role": "user", "content": "Вызови read_number."}],
        model=local.MODEL_ID,
        tools=tools,
        tool_choice="required",
        max_tokens=128,
        stream=True,
        stream_options={"include_usage": True},
    )
    calls, usages, terminals = [], [], []
    async for chunk in streamed:
        if chunk.usage:
            usages.append(chunk.usage.total_tokens)
        for choice in chunk.choices:
            calls.extend(choice.delta.tool_calls or [])
            if choice.finish_reason:
                terminals.append(choice.finish_reason)
    assert len(calls) == 1 and calls[0].function.name == "read_number", "sdk_stream_tool_invalid"
    assert len(usages) == 1 and usages[0] > 0, "sdk_stream_usage_invalid"
    assert terminals == ["tool_calls"], "sdk_stream_terminal_invalid"
    await local.get_openai_client().close()
    return {
        "registry": "local",
        "tools": True,
        "vision": False,
        "sdk": True,
        "stream_tools": True,
        "stream_usage_receipts": len(usages),
    }


if __name__ == "__main__":
    try:
        result = asyncio.run(exercise(json.load(sys.stdin)["key"]))
        print(json.dumps(result), flush=True)
    except Exception as error:
        code = str(error) if isinstance(error, AssertionError) else "provider_probe_failed"
        print(json.dumps({"failure": code}), flush=True)
        raise SystemExit(1) from None
