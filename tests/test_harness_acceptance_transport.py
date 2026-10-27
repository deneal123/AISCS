"""The acceptance double replaces model HTTP only, preserving each wire dialect."""

import json

import httpx
import pytest

from scripts.harness_live.model_transport import ScriptedProvider


@pytest.mark.parametrize(
    "provider,model",
    [
        ("gigachat", "GigaChat-3-Lightning"),
        ("routerai", "openai/gpt-4o-mini"),
        ("openai", "gpt-4o-mini"),
    ],
)
@pytest.mark.parametrize("stream", [False, True])
def test_real_sdk_receives_its_own_tool_call_dialect(monkeypatch, provider, model, stream):
    monkeypatch.setenv("HARNESS_ACCEPTANCE_PROVIDER", provider)
    owner = ScriptedProvider()
    payload = {
        "model": model,
        "stream": stream,
        "messages": [{"role": "user", "content": "create"}],
    }
    if provider == "gigachat":
        payload["functions"] = [{"name": "ide_list_files"}]
    else:
        payload["tools"] = [{"type": "function", "function": {"name": "ide_list_files"}}]
    response = owner.completion(
        httpx.Request("POST", "https://provider/chat/completions", json=payload)
    )
    data = (
        json.loads(response.content.decode().split("data: ", 1)[1].split("\n\n", 1)[0])
        if stream
        else response.json()
    )
    choice = data["choices"][0]
    message = choice["delta" if stream else "message"]
    if provider == "gigachat":
        assert choice["finish_reason"] == "function_call"
        assert message["function_call"] == {"name": "ide_list_files", "arguments": {"path": ""}}
        assert "tool_calls" not in message
    else:
        assert choice["finish_reason"] == "tool_calls"
        assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {"path": ""}
        assert ("index" in message["tool_calls"][0]) == stream
        assert "function_call" not in message
    assert owner.tool_names == ["ide_list_files"]


def test_completed_history_tracks_repeated_canonical_tool_calls():
    messages = []
    for index, name in enumerate(["ide_read_file", "ide_run_command", "ide_read_file"]):
        call_id = f"call-{index}"
        messages.extend(
            [
                {"role": "assistant", "tool_calls": [{"id": call_id, "function": {"name": name}}]},
                {"role": "tool", "tool_call_id": call_id, "content": "{}"},
            ]
        )
    assert ScriptedProvider.completed_tools(messages) == [
        "ide_read_file",
        "ide_run_command",
        "ide_read_file",
    ]


def test_changing_private_state_fixture_detects_stale_recovery(monkeypatch):
    monkeypatch.setenv("HARNESS_ACCEPTANCE_PROVIDER", "gigachat")
    owner = ScriptedProvider()
    payload = {
        "model": owner.model,
        "messages": [{"role": "user", "content": "Создай скрипт"}],
        "functions": [{"name": "ide_list_files"}],
    }
    first = owner.completion(
        httpx.Request("POST", "https://provider/chat/completions", json=payload)
    )
    message = first.json()["choices"][0]["message"]
    payload["messages"].extend(
        [
            message,
            {"role": "function", "name": "ide_list_files", "content": "{}"},
        ]
    )
    payload["messages"][-2]["functions_state_id"] = "STALE_PRIVATE_STATE"
    with pytest.raises(AssertionError, match="acceptance_provider_state_stale"):
        owner.completion(httpx.Request("POST", "https://provider/chat/completions", json=payload))


@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai"])
def test_contract_detection_is_structural_and_clarification_preserves_provider_dialect(
    monkeypatch, provider
):
    monkeypatch.setenv("HARNESS_ACCEPTANCE_PROVIDER", provider)
    monkeypatch.setenv("HARNESS_ACCEPTANCE_SCENARIO", "clarify")
    owner = ScriptedProvider()
    payload = {
        "model": owner.model,
        "messages": [
            {"role": "system", "content": "Структура вызова не зависит от текста инструкции."},
        ],
    }
    if provider == "gigachat":
        payload["functions"] = [{"name": "submit_task_contract"}]
    else:
        payload["tools"] = [{"type": "function", "function": {"name": "submit_task_contract"}}]
    for answered in (False, True):
        if answered:
            content = '{"answer":{"text":"hello_world.py"}}'
            if provider == "gigachat":
                content = json.dumps({"result": content})
            payload["messages"].append(
                {
                    "role": "function" if provider == "gigachat" else "tool",
                    "content": content,
                }
            )
        response = owner.completion(
            httpx.Request("POST", "https://provider/chat/completions", json=payload)
        )
        message = response.json()["choices"][0]["message"]
        raw = (
            message["function_call"]["arguments"]
            if provider == "gigachat"
            else json.loads(message["tool_calls"][0]["function"]["arguments"])
        )
        assert raw["needs_clarification"] is not answered
        assert bool(raw["question"]) is not answered
    assert owner.tool_names == [] and owner.completions == 2
