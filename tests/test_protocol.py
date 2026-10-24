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
                    "content": value.get("response")
                    if isinstance(value, dict) and value.get("tool_name") is None
                    else json.dumps(value),
                },
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 9, "total_tokens": 21},
    }
    if isinstance(value, dict) and value.get("tool_name") is not None:
        result["choices"][0].update(
            finish_reason="tool_calls",
            message={
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_fixed",
                        "type": "function",
                        "function": {
                            "name": value["tool_name"],
                            "arguments": json.dumps(value["arguments"]),
                        },
                    }
                ],
            },
        )
    result.update(changes)
    return result


def test_compile_required_preserves_original_and_uses_native_tools(body):
    before = deepcopy(body)
    compiled = compile_request(body)
    assert body == before and compiled.structured_tools and not compiled.allow_final
    assert compiled.body["tools"] == body["tools"]
    assert compiled.body["tool_choice"] == "required"
    assert compiled.body["parallel_tool_calls"] is False
    assert compiled.body["stream"] is False
    assert compiled.body["max_tokens"] == 128
    assert "response_format" not in compiled.body
    assert compiled.body["messages"][:-1] == body["messages"]
    assert compiled.body["messages"][-1] == {"role": "assistant", "content": "<tool_call>\n"}
    assert compiled.body["continue_final_message"] == "content"
    assert compiled.body["add_generation_prompt"] is False


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
    assert resumed.body["messages"][-3]["tool_calls"][0]["id"] == call["id"]
    assert resumed.body["messages"][-2] == {
        "role": "tool",
        "tool_call_id": call["id"],
        "content": "opaque-731",
    }


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


@pytest.mark.parametrize("fault", ["empty", "message", "function", "parallel", "arguments"])
def test_malformed_native_reply_preserves_receipt_and_usage(body, fault):
    raw = completion({"tool_name": "read_number", "arguments": {"step": 1}})
    message = raw["choices"][0]["message"]
    if fault == "empty":
        raw["choices"] = []
    elif fault == "message":
        raw["choices"][0]["message"] = []
    elif fault == "function":
        message["tool_calls"][0]["function"] = None
    elif fault == "parallel":
        message["tool_calls"].append(deepcopy(message["tool_calls"][0]))
    else:
        message["tool_calls"][0]["function"]["arguments"] = '{"step":NaN}'
    result = normalize_response(raw, compile_request(body))
    assert result["id"] == raw["id"] and result["usage"] == raw["usage"]
    assert result["local_protocol_error"] == "tool_response_invalid"
    assert result["choices"][0]["finish_reason"] == "length"
    assert not result["choices"][0]["message"].get("tool_calls")


def test_none_and_named_choice_cannot_execute_another_function(body):
    raw = completion({"tool_name": "read_number", "arguments": {"step": 1}})
    body["tool_choice"] = "none"
    result = normalize_response(raw, compile_request(body))
    assert result["local_protocol_error"] == "tool_response_invalid"
    body["tools"].append(
        {
            "type": "function",
            "function": {
                "name": "other",
                "parameters": {"type": "object"},
            },
        }
    )
    body["tool_choice"] = {"type": "function", "function": {"name": "other"}}
    compiled = compile_request(body)
    assert compiled.body["tool_choice"] == "required"
    assert [tool["function"]["name"] for tool in compiled.body["tools"]] == ["other"]
    assert compiled.body["messages"][-1]["content"] == (
        '<tool_call>\n{"name": "other", "arguments": '
    )
    result = normalize_response(raw, compiled)
    assert result["local_protocol_error"] == "tool_response_invalid"
    assert result["usage"] == raw["usage"]


def test_auto_can_return_actual_text_and_stream_usage_once(body):
    body.update(tool_choice="auto", stream=True, stream_options={"include_usage": True})
    compiled = compile_request(body)
    assert compiled.body["messages"] == body["messages"]
    assert "continue_final_message" not in compiled.body
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
