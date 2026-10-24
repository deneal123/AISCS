"""HTTP и SSE через настоящий listener; подменён только transport локального inference."""

import json
import threading
import urllib.error
import urllib.request
from unittest.mock import Mock

import pytest

from local_llm.service.domain.model import MODEL_ID
from local_llm.service.domain.protocol.contracts import ProtocolFailure
from local_llm.service.presentation.http import Gateway

KEY = "synthetic-local-key-" * 3


@pytest.fixture
def gateway():
    raw = {
        "id": "local-fixed",
        "created": 1,
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "Проверка",
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    upstream = Mock(return_value=raw)
    server = Gateway(("127.0.0.1", 0), KEY, upstream=upstream)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    address = "http://127.0.0.1:" + str(server.server_port)
    try:
        yield address, upstream, server, raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def request(gateway, body=None, *, key=KEY, path="/v1/chat/completions"):
    return urllib.request.urlopen(
        urllib.request.Request(
            gateway[0] + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        ),
        timeout=5,
    )


def body(**changes):
    return {"model": MODEL_ID, "messages": [{"role": "user", "content": "Проверка"}], **changes}


def test_anonymous_and_invalid_model_do_not_dispatch(gateway):
    for payload, key, expected in [(body(), "", 401), (body(model="PRIVATE_MODEL"), KEY, 404)]:
        with pytest.raises(urllib.error.HTTPError) as caught:
            request(gateway, payload, key=key)
        assert caught.value.code == expected
        assert b"PRIVATE_MODEL" not in caught.value.read()
    gateway[1].assert_not_called()


def test_request_has_one_inference_and_no_cache(gateway):
    with request(gateway, body()) as response:
        result = json.load(response)
        assert response.headers["Cache-Control"] == "no-store"
    assert result["usage"]["total_tokens"] == 12
    gateway[1].assert_called_once()
    assert gateway[1].call_args.args[1]["stream"] is False


def test_busy_gate_rejects_without_dispatch_or_queue(gateway):
    server = gateway[2]
    assert server.completions.slot.acquire(blocking=False)
    try:
        with pytest.raises(urllib.error.HTTPError) as caught:
            request(gateway, body())
        assert caught.value.code == 429
        gateway[1].assert_not_called()
    finally:
        server.completions.slot.release()
    with request(gateway, body()) as response:
        assert response.status == 200


def test_stream_preserves_exact_usage_and_one_terminal(gateway):
    with request(gateway, body(stream=True, stream_options={"include_usage": True})) as response:
        data = response.read().decode()
        assert response.headers.get_content_type() == "text/event-stream"
    assert data.count("data: [DONE]") == 1
    chunks = [json.loads(line[6:]) for line in data.splitlines() if line.startswith("data: {")]
    assert sum("usage" in chunk for chunk in chunks) == 1
    assert chunks[-1]["usage"] == gateway[3]["usage"]
    gateway[1].assert_called_once()


def test_gateway_compiles_tools_without_executing_or_retrying(gateway):
    gateway[3]["choices"][0]["message"]["content"] = json.dumps(
        {
            "tool_name": "read_file",
            "arguments": {"path": "a.py"},
        }
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]
    with request(gateway, body(tools=tools, tool_choice="required")) as response:
        result = json.load(response)
    assert result["choices"][0]["finish_reason"] == "tool_calls"
    call = result["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "read_file"
    assert result["usage"] == gateway[3]["usage"]
    gateway[1].assert_called_once()
    sent = gateway[1].call_args.args[1]
    assert "tools" not in sent and "tool_choice" not in sent
    assert sent["response_format"]["type"] == "json_schema"


def test_upstream_failure_has_no_private_message_and_no_retry(gateway):
    gateway[1].side_effect = ProtocolFailure("upstream_unavailable", 503)
    with pytest.raises(urllib.error.HTTPError) as caught:
        request(gateway, body())
    assert caught.value.code == 503
    gateway[1].assert_called_once()
    assert caught.value.headers["Cache-Control"] == "no-store"
