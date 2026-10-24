"""Обязательный вызов не превращается в текст, invalid/length сохраняют usage без повторов."""

import json
from copy import deepcopy

import pytest

from local_llm.service.domain.model import MODEL_ID
from local_llm.service.domain.protocol.compiler import compile_request
from local_llm.service.domain.protocol.contracts import ProtocolFailure
from local_llm.service.domain.protocol.response import normalize_response, stream_events


@pytest.fixture
def body():
    return {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": "Прочитай число проверки."}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "read_number",
                    "description": "Прочитать число проверки",
                    "parameters": {
                        "type": "object",
                        "properties": {"step": {"type": "integer", "minimum": 1}},
                        "required": ["step"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
        "tool_choice": "required",
        "max_tokens": 128,
    }


def completion(value, **changes):
    result = {
        "id": "completion-fixed",
        "created": 1,
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(value),
                },
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 9, "total_tokens": 21},
    }
    result.update(changes)
    return result


def test_compile_required_preserves_original_and_removes_native_parser(body):
    before = deepcopy(body)
    compiled = compile_request(body)
    assert body == before and compiled.structured_tools and not compiled.allow_final
    assert "tools" not in compiled.body and "tool_choice" not in compiled.body
    assert compiled.body["stream"] is False
    assert compiled.body["max_tokens"] == 128
    schema = compiled.body["response_format"]["json_schema"]["schema"]
    assert len(schema["oneOf"]) == 1
    assert schema["oneOf"][0]["properties"]["tool_name"] == {"const": "read_number"}


@pytest.mark.parametrize("reference", ["$dynamicRef", "$recursiveRef"])
def test_unsupported_reference_cannot_enable_external_resolution(body, reference):
    body["tools"][0]["function"]["parameters"][reference] = "http://private.invalid/schema"
    with pytest.raises(ProtocolFailure, match="unsupported_schema_reference"):
        compile_request(body)


def test_round_trip_has_stable_tool_identity_and_same_usage(body):
    compiled = compile_request(body)
    raw = completion({"tool_name": "read_number", "arguments": {"step": 1}})
    reply = normalize_response(raw, compiled)
    assert reply == normalize_response(raw, compiled)
    assert reply["usage"] == raw["usage"]
    choice = reply["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    call = choice["message"]["tool_calls"][0]
    assert call["function"] == {"name": "read_number", "arguments": '{"step": 1}'}
    body["messages"].extend(
        [
            choice["message"],
            {"role": "tool", "tool_call_id": call["id"], "content": "opaque-731"},
        ]
    )
    resumed = compile_request(body)
    assert all(
        not item.get("tool_calls") and item["role"] != "tool" for item in resumed.body["messages"]
    )
    assert "opaque-731" in resumed.body["messages"][-1]["content"]


@pytest.mark.parametrize(
    "value",
    [
        {"tool_name": None, "response": "готово"},
        {"tool_name": "unknown", "arguments": {}},
        {"tool_name": "read_number", "arguments": {"step": 0}},
        {"tool_name": "read_number", "arguments": {"step": "one"}},
        {"tool_name": "read_number", "arguments": {"step": 1, "secret": "PRIVATE_MARKER"}},
    ],
)
def test_invalid_output_never_becomes_call_or_final_and_preserves_cost(body, value):
    raw = completion(value)
    result = normalize_response(raw, compile_request(body))
    assert result["usage"] == raw["usage"]
    assert result["local_protocol_error"] == "tool_response_invalid"
    assert result["choices"][0]["finish_reason"] == "length"
    assert not result["choices"][0]["message"].get("tool_calls")
    assert "PRIVATE_MARKER" not in json.dumps(result)


def test_length_is_not_accepted_even_if_json_looks_complete(body):
    raw = completion({"tool_name": "read_number", "arguments": {"step": 1}})
    raw["choices"][0]["finish_reason"] = "length"
    result = normalize_response(raw, compile_request(body))
    assert result["choices"][0]["finish_reason"] == "length"
    assert result["usage"] == raw["usage"]


def test_auto_can_return_actual_text_and_stream_usage_once(body):
    body.update(tool_choice="auto", stream=True, stream_options={"include_usage": True})
    compiled = compile_request(body)
    result = normalize_response(completion({"tool_name": None, "response": "Ответ"}), compiled)
    chunks = list(stream_events(result, include_usage=True))
    assert chunks[-1] == b"data: [DONE]\n\n"
    decoded = [json.loads(chunk.decode()[6:]) for chunk in chunks[:-1]]
    assert decoded[0]["choices"][0]["delta"]["content"] == "Ответ"
    assert sum("usage" in item for item in decoded) == 1
    assert decoded[-1]["usage"]["total_tokens"] == 21


@pytest.mark.parametrize("fault", ["model", "forced", "schema", "external", "pending"])
def test_invalid_request_is_rejected_before_inference(body, fault):
    if fault == "model":
        body["model"] = "other-model"
    elif fault == "forced":
        body["tool_choice"] = {"type": "function", "function": {"name": "unknown"}}
    elif fault == "schema":
        body["tools"][0]["function"]["parameters"]["type"] = "not-a-type"
    elif fault == "external":
        body["tools"][0]["function"]["parameters"]["$ref"] = "https://private.example/schema"
    else:
        body["messages"].append(
            {"role": "tool", "tool_call_id": "not-pending", "content": "PRIVATE"}
        )
    with pytest.raises(ProtocolFailure) as caught:
        compile_request(body)
    assert "PRIVATE" not in str(caught.value)
