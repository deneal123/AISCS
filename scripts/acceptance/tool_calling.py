"""Настоящая бесплатная tool-calling проба; печатаются только закрытые результаты."""

import json
import secrets
import sys
import urllib.error
import urllib.request

MODEL = "lfm2.5-1.2b-instruct"
PROGRESS = {"verified_rounds": 0, "calls": 0, "finish_reason": None}


def probe(
    key: str, base_url: str, rounds: int = 1, choice: str = "required", suite: str = "arithmetic"
) -> dict:
    PROGRESS.update(verified_rounds=0, calls=0, finish_reason=None)
    if base_url != "http://local-llm:8080":
        raise ValueError("probe_address_invalid")
    if not 1 <= rounds <= 16:
        raise ValueError("probe_rounds_invalid")
    if choice not in {"required", "auto", "named"}:
        raise ValueError("probe_choice_invalid")
    if suite not in {"arithmetic", "opaque"}:
        raise ValueError("probe_suite_invalid")

    def request(path, body=None, *, authenticated=True):
        headers = {"Authorization": "Bearer " + key} if authenticated else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        with urllib.request.urlopen(
            urllib.request.Request(
                base_url + path,
                data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
                headers=headers,
            ),
            timeout=120,
        ) as response:
            content = response.read(262145)
            if len(content) > 262144:
                raise ValueError("probe_output_limit")
            return json.loads(content)

    try:
        request("/v1/models", authenticated=False)
    except urllib.error.HTTPError as error:
        assert error.code == 401, "anonymous_status_invalid"
    else:
        raise ValueError("anonymous_model_access")
    assert MODEL in [item["id"] for item in request("/v1/models")["data"]], "model_missing"
    messages = [
        {
            "role": "system",
            "content": (
                "Ты проверяешь локальный инструмент сложения. Для каждой новой суммы "
                "обязательно вызывай add_numbers. После получения результата отвечай "
                "только JSON-объектом с целочисленным полем result, без объяснений."
            ),
        }
    ]
    tool = {
        "type": "function",
        "function": {
            "name": "add_numbers",
            "description": "Сложить два целых числа и вернуть точный результат.",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "required": ["a", "b"],
                "additionalProperties": False,
            },
        },
    }
    if suite == "opaque":
        messages[0]["content"] = (
            "Для каждого запроса служебного кода вызывай read_receipt с номером шага. "
            "Код заранее неизвестен, его нельзя угадать или вычислить. Только после "
            "получения результата верни JSON с полем value и кодом текущего шага. "
            "Не используй коды предыдущих шагов."
        )
        tool = {
            "type": "function",
            "function": {
                "name": "read_receipt",
                "description": "Прочитать непредсказуемый код текущего шага.",
                "parameters": {
                    "type": "object",
                    "properties": {"step": {"type": "integer"}},
                    "required": ["step"],
                    "additionalProperties": False,
                },
            },
        }
    tool_name = tool["function"]["name"]
    tokens = calls = 0
    for index in range(rounds):
        a, b = index + 2, 3
        expected = {"result": a + b} if suite == "arithmetic" else {"value": secrets.token_hex(4)}
        arguments = {"a": a, "b": b} if suite == "arithmetic" else {"step": index + 1}
        prompt = (
            f"Сложи {a} и {b} через инструмент."
            if suite == "arithmetic"
            else f"Прочитай служебный код для шага {index + 1} через инструмент."
        )
        messages.append({"role": "user", "content": prompt})
        first = request(
            "/v1/chat/completions",
            {
                "model": MODEL,
                "messages": messages,
                "tools": [tool],
                "tool_choice": (
                    {"type": "function", "function": {"name": tool_name}}
                    if choice == "named"
                    else choice
                ),
                "parallel_tool_calls": False,
                "max_tokens": 128,
                "temperature": 0.1,
            },
        )
        calls += 1
        PROGRESS.update(calls=calls, finish_reason=first["choices"][0].get("finish_reason"))
        tokens += first["usage"]["total_tokens"]
        reply = first["choices"][0]["message"]
        assert len(reply.get("tool_calls", [])) == 1, "tool_call_missing"
        call = reply["tool_calls"][0]
        assert call["function"]["name"] == tool_name, "tool_name_invalid"
        assert json.loads(call["function"]["arguments"]) == arguments, "tool_args_invalid"
        messages.extend(
            [
                reply,
                {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(expected)},
            ]
        )
        second = request(
            "/v1/chat/completions",
            {
                "model": MODEL,
                "messages": messages,
                "tools": [tool],
                "tool_choice": "none",
                "max_tokens": 32,
                "temperature": 0.1,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "result",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": (
                                {"result": {"type": "integer"}}
                                if suite == "arithmetic"
                                else {"value": {"type": "string"}}
                            ),
                            "required": ["result" if suite == "arithmetic" else "value"],
                            "additionalProperties": False,
                        },
                    },
                },
            },
        )
        calls += 1
        PROGRESS.update(calls=calls, finish_reason=second["choices"][0].get("finish_reason"))
        tokens += second["usage"]["total_tokens"]
        final = second["choices"][0]["message"]
        assert json.loads(final["content"]) == expected, "tool_result_not_used"
        messages.append(final)
        PROGRESS["verified_rounds"] = index + 1
    return {
        "model": MODEL,
        "choice": choice,
        "suite": suite,
        "verified_rounds": rounds,
        "calls": calls,
        "tokens": tokens,
    }


if __name__ == "__main__":
    try:
        arguments = json.load(sys.stdin)
        result = probe(
            arguments["key"],
            arguments["base_url"],
            arguments.get("rounds", 1),
            arguments.get("choice", "required"),
            arguments.get("suite", "arithmetic"),
        )
        print(json.dumps(result), flush=True)
    except Exception as error:
        # Не печатаем ответ модели, URL, transcript или транспортную диагностику.
        code = (
            str(error) if isinstance(error, (ValueError, AssertionError)) else "probe_unavailable"
        )
        safe = (
            code
            if code.replace("_", "").isascii() and code.replace("_", "").isalpha()
            else "probe_failed"
        )
        print(json.dumps({"failure": safe, **PROGRESS}), flush=True)
        raise SystemExit(1) from None
