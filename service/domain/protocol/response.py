"""Ответ OpenAI и buffered SSE; usage относится к единственному фактическому вызову."""

import hashlib
import json
from copy import deepcopy

from jsonschema import Draft202012Validator

from .contracts import CompiledRequest, ProtocolFailure


def normalize_response(raw: dict, request: CompiledRequest) -> dict:
    result = deepcopy(raw)
    if not request.structured_tools:
        return result
    try:
        choice = result["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ValueError
        value = json.loads(choice["message"]["content"])
        name = value["tool_name"]
        if name is None and not request.allow_final:
            raise ValueError
        if name is None:
            response = value["response"]
            if not request.structured_response and not isinstance(response, str):
                raise ValueError
            choice["message"] = {
                "role": "assistant",
                "content": (
                    json.dumps(response, ensure_ascii=False)
                    if request.structured_response
                    else response
                ),
            }
            choice["finish_reason"] = "stop"
        else:
            arguments = value["arguments"]
            if name not in request.functions or not isinstance(arguments, dict):
                raise ValueError
            if not Draft202012Validator(request.functions[name]["parameters"]).is_valid(arguments):
                raise ValueError
            identity = hashlib.sha256((str(result["id"]) + name).encode()).hexdigest()[:24]
            choice["message"] = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_" + identity,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                ],
            }
            choice["finish_reason"] = "tool_calls"
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
