"""Живой ретест обычного ответа и добровольного завершения tool-loop на dev."""

import json
import os
import sys
import time
import urllib.request


def exercise():
    from service.domain.subagents.general import GENERAL_PROMPT
    from service.domain.tools.function_tools import fetch_url

    key = os.environ["AGENTS__LOCAL_API_KEY"]
    base = "http://local-llm:8080/v1"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, body=None):
        req = urllib.request.Request(
            base + path,
            data=json.dumps(body, ensure_ascii=False).encode() if body else None,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        with opener.open(req, timeout=120) as response:
            return json.load(response)

    catalog = request("/models")
    print(json.dumps({"catalog": catalog}), flush=True)
    tools = [
        {
            "type": "function",
            "function": {
                "name": fetch_url.name,
                "description": fetch_url.description,
                "parameters": fetch_url.params_json_schema,
            },
        }
    ]
    failures = []
    for name, prompt, offered in [
        ("hello_plain", "привет", []),
        ("hello_auto", "привет", tools),
        ("unclear_auto", "оиили", tools),
        ("url_auto", "Прочитай https://example.com/ и перескажи страницу.", tools),
    ]:
        started = time.monotonic()
        body = {
            "model": "qwen2.5-1.5b-instruct",
            "messages": [
                {"role": "system", "content": GENERAL_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 256,
        }
        if offered:
            body.update(tools=offered, tool_choice="auto")
        result = request("/chat/completions", body)
        choice = result["choices"][0]
        message = choice["message"]
        calls = message.get("tool_calls") or []
        valid = (
            len(calls) == 1 and calls[0]["function"]["name"] == "fetch_url"
            if name == "url_auto"
            else not calls and bool((message.get("content") or "").strip())
        )
        if not valid or result.get("local_protocol_error") or choice["finish_reason"] == "length":
            failures.append(name)
        print(
            json.dumps(
                {
                    "case": name,
                    "seconds": round(time.monotonic() - started, 2),
                    "finish_reason": choice["finish_reason"],
                    "text": message.get("content"),
                    "tool_names": [c["function"]["name"] for c in message.get("tool_calls", [])],
                    "protocol_error": result.get("local_protocol_error"),
                    "usage": result.get("usage"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    print(json.dumps({"failed_cases": failures}), flush=True)
    return bool(failures)


if __name__ == "__main__":
    sys.exit(exercise())
