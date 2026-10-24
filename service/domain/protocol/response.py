"""Ответ OpenAI и buffered SSE; usage относится к единственному фактическому вызову."""

import json
from copy import deepcopy

from jsonschema import Draft202012Validator

from .compiler import response_schema
from .contracts import CompiledRequest, ProtocolFailure


def normalize_response(raw: dict, request: CompiledRequest) -> dict:
    result = deepcopy(raw)
    try:
        if len(result["choices"]) != 1:
            raise ValueError
        choice = result["choices"][0]
        message = choice["message"]
        calls = message.get("tool_calls") or []
        content = message.get("content")
        if message.get("role") != "assistant" or (
            content is not None and not isinstance(content, str)
        ):
            raise ValueError
        if calls:
            if (
                not isinstance(calls, list)
                or len(calls) != 1
                or choice.get("finish_reason") != "tool_calls"
            ):
                raise ValueError
            call = calls[0]
            function = call["function"]
            identity = call["id"]
            name = function["name"]
            if (
                call.get("type") != "function"
                or not isinstance(identity, str)
                or not 1 <= len(identity) <= 128
            ):
                raise ValueError
            if name not in request.functions or not isinstance(function["arguments"], str):
                raise ValueError
            arguments = json.loads(function["arguments"])
            if not isinstance(arguments, dict):
                raise ValueError
            json.dumps(arguments, allow_nan=False)
            if not Draft202012Validator(request.functions[name]["parameters"]).is_valid(arguments):
                raise ValueError
            choice["message"] = {
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": identity,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                ],
            }
        elif not request.allow_final or choice.get("finish_reason") not in {"stop", "length"}:
            raise ValueError
        elif request.structured_response and choice.get("finish_reason") != "length":
            schema, _ = response_schema(request.body)
            value = json.loads(content)
            json.dumps(value, allow_nan=False)
            if not Draft202012Validator(schema).is_valid(value):
                raise ValueError
    except (ValueError, KeyError, TypeError, IndexError):
        # Usage сохраняется. Нет внутреннего второго inference или фиктивного инструмента.
        if not result.get("choices"):
            raise ProtocolFailure("upstream_protocol_invalid", 502) from None
        result["choices"] = [
            {
                "index": 0,
                "finish_reason": "length",
                "message": {
                    "role": "assistant",
                    "content": "Не удалось завершить структурированный вызов инструмента.",
                },
            }
        ]
        result["local_protocol_error"] = "tool_response_invalid"
    return result


def stream_events(result: dict, *, include_usage: bool):
    base = {name: result[name] for name in ("id", "model", "created")}
    base["object"] = "chat.completion.chunk"
    choice = result["choices"][0]
    message = choice["message"]
    delta = {"role": "assistant"}
    if message.get("tool_calls"):
        delta["tool_calls"] = [
            {"index": index, **call} for index, call in enumerate(message["tool_calls"])
        ]
    else:
        delta["content"] = message.get("content") or ""
    values = [
        {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": choice["finish_reason"]}]},
    ]
    if include_usage:
        values.append({**base, "choices": [], "usage": result["usage"]})
    for value in values:
        yield ("data: " + json.dumps(value, ensure_ascii=False) + "\n\n").encode()
    yield b"data: [DONE]\n\n"
