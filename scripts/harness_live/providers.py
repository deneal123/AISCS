"""Model-only acceptance profiles, with no real provider network fallback."""

import json

MODELS = {
    "gigachat": "GigaChat-3-Lightning",
    "routerai": "openai/gpt-4o-mini",
    "openai": "gpt-4o-mini",
}


def function_message(payload, function, *, provider, index):
    name, args = function
    if provider == "gigachat":
        assert "functions" in payload and "tools" not in payload
        assert name in {item["name"] for item in payload["functions"]}
        return {"function_call": {"name": name, "arguments": args}}, "function_call"
    assert "tools" in payload and "functions" not in payload
    assert name in {item["function"]["name"] for item in payload["tools"]}
    call = {
        "id": f"acceptance-call-{index}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }
    if payload.get("stream"):
        call["index"] = 0
    return {"tool_calls": [call]}, "tool_calls"
