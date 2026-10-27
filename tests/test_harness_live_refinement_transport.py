"""Сам double проверяется отдельно: без рекомендации он не разыгрывает успешный probe."""

import json

import httpx
import pytest

from scripts.harness_live.model_transport import ScriptedProvider
from scripts.harness_live.providers import MODELS
from scripts.harness_live.refinement import INSTRUCTION, TOOL


def send(provider, names, messages):
    functions = [{"name": name, "parameters": {"type": "object"}} for name in names]
    payload = {"model": MODELS[provider.provider], "messages": messages}
    if provider.provider == "gigachat":
        payload["functions"] = functions
    else:
        payload["tools"] = [{"type": "function", "function": function} for function in functions]
    return provider.completion(
        httpx.Request("POST", "http://model.invalid/chat/completions", json=payload)
    ).json()


@pytest.mark.parametrize("name", ["gigachat", "routerai", "openai"])
def test_refinement_contrast_requires_checkpointed_guidance(monkeypatch, name):
    monkeypatch.setenv("HARNESS_ACCEPTANCE_SCENARIO", "refine")
    monkeypatch.setenv("HARNESS_ACCEPTANCE_PROVIDER", name)
    provider = ScriptedProvider()
    original = [{"role": "user", "content": "Создай и проверь файл в рабочем каталоге."}]
    missing = send(provider, ["ide_list_files"], original)
    assert missing["choices"][0]["finish_reason"] == "stop" and not provider.tool_names
    proposed = send(provider, [TOOL], original)
    message = proposed["choices"][0]["message"]
    if name == "gigachat":
        value = message["function_call"]["arguments"]
    else:
        value = json.loads(message["tool_calls"][0]["function"]["arguments"])
    assert value["instruction"] == INSTRUCTION and not provider.tool_names
    # Один факт, что meta-вызов состоялся, не меняет результат следующего model call.
    without_guidance = send(provider, ["ide_list_files"], original)
    assert without_guidance["choices"][0]["finish_reason"] == "stop" and not provider.tool_names
    probe = send(
        provider, ["ide_list_files"], [*original, {"role": "user", "content": INSTRUCTION}]
    )
    assert probe["choices"][0]["finish_reason"] in {"function_call", "tool_calls"}
    assert provider.tool_names == ["ide_list_files"]
