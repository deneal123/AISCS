"""Одинаковый ограниченный корпус: нет платных провайдеров или исполнения команд."""

import json
import secrets
import time

from local_llm.service.domain.model import MODEL_ID

TOOL = {
    "type": "function",
    "function": {
        "name": "read_receipt",
        "description": "Прочитать неизвестный заранее служебный код по номеру шага.",
        "parameters": {
            "type": "object",
            "properties": {"step": {"type": "integer"}},
            "required": ["step"],
            "additionalProperties": False,
        },
    },
}
SYSTEM = (
    "Ты русскоязычный помощник. Отвечай на запрос пользователя. Не вызывай инструменты "
    "без необходимости. Для чтения служебного кода используй read_receipt; не угадывай код. "
    "Получив код, сообщи его пользователю и закончи ответ, не вызывая инструмент повторно."
)


def sampling_body(body, profile):
    if profile == "qwen3-nonthinking":
        return {**body, "temperature": 0.7, "top_p": 0.8, "presence_penalty": 1.5}
    if profile == "qwen35-text":
        return {**body, "temperature": 1.0, "top_p": 1.0, "presence_penalty": 2.0}
    if profile == "precise":
        # Отдельный эксперимент: копирование tool-result без штрафа за повтор токенов.
        return {**body, "temperature": 0.6, "top_p": 0.95, "presence_penalty": 0.0}
    if profile != "deterministic":
        raise ValueError("comparison_profile_invalid")
    return body


def exercise_history(request, *, rounds=16, on_step=None):
    """Продолженная история: новый непредсказуемый результат на каждом шаге."""
    if not 1 <= rounds <= 16:
        raise ValueError("comparison_rounds_invalid")
    body = {
        "model": MODEL_ID,
        "messages": [{"role": "system", "content": SYSTEM}],
        "tools": [TOOL],
        "tool_choice": "auto",
        "temperature": 0,
        "seed": 0,
        "max_tokens": 256,
    }
    verified = calls = tokens = 0
    failure = ""
    try:
        for step in range(1, rounds + 1):
            body["messages"].append({"role": "user", "content": f"Прочитай код шага {step}."})
            calls += 1
            result = request(body)
            tokens += result.get("usage", {}).get("total_tokens", 0)
            reply = result["choices"][0]
            message = reply["message"]
            invoked = message.get("tool_calls") or []
            if reply.get("finish_reason") != "tool_calls" or len(invoked) != 1:
                raise ValueError("history_tool_missing")
            call = invoked[0]
            arguments = json.loads(call["function"]["arguments"])
            if (
                call["function"]["name"] != "read_receipt"
                or arguments != {"step": step}
                or type(arguments.get("step")) is not int
            ):
                raise ValueError("history_arguments_invalid")
            receipt = secrets.token_hex(8)
            body["messages"].extend(
                [
                    message,
                    {"role": "tool", "tool_call_id": call["id"], "content": receipt},
                ]
            )
            calls += 1
            result = request(body)
            tokens += result.get("usage", {}).get("total_tokens", 0)
            reply = result["choices"][0]
            message = reply["message"]
            if (
                reply.get("finish_reason") != "stop"
                or message.get("tool_calls")
                or receipt not in (message.get("content") or "")
            ):
                raise ValueError("history_final_invalid")
            body["messages"].append(message)
            verified = step
            if on_step is not None:
                on_step({"verified_rounds": verified, "inferences": calls})
    except Exception as error:
        failure = str(error) if type(error) is ValueError else "history_request_failed"
        if failure not in {
            "history_tool_missing",
            "history_arguments_invalid",
            "history_final_invalid",
        }:
            failure = "history_request_failed"
    return {
        "passed": verified == rounds,
        "verified_rounds": verified,
        "inferences": calls,
        "tokens": tokens,
        "failure": failure,
    }


def exercise(request, *, repeats=3, on_case=None):
    """request — тот же gateway; результат не содержит текстов или секретов."""
    if not 1 <= repeats <= 10:
        raise ValueError("comparison_repeats_invalid")
    results = []
    for repeat in range(repeats):
        for case, prompt, offered, choice in (
            ("hello_plain", "Привет!", False, "auto"),
            ("hello_auto", "Привет!", True, "auto"),
            ("unclear_auto", "оиили", True, "auto"),
            ("receipt_auto", "Прочитай служебный код шага 1.", True, "auto"),
            ("receipt_required", "Прочитай служебный код шага 1.", True, "required"),
            ("receipt_named", "Прочитай служебный код шага 1.", True, "named"),
        ):
            row = run_case(request, repeat, case, prompt, offered, choice)
            results.append(row)
            if on_case is not None:
                on_case(row)
    return {"passed": all(row["passed"] for row in results), "cases": results}


def run_case(request, repeat, case, prompt, offered, choice):
    body = {
        "model": MODEL_ID,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "temperature": 0,
        "seed": repeat,
        "max_tokens": 256,
    }
    if offered:
        body.update(
            tools=[TOOL],
            tool_choice=(
                {"type": "function", "function": {"name": "read_receipt"}}
                if choice == "named"
                else choice
            ),
        )
    started = time.monotonic()
    calls = tokens = tools = 0
    failure = ""
    receipt = secrets.token_hex(8)
    try:
        for _ in range(3):
            calls += 1
            result = request(body)
            tokens += result.get("usage", {}).get("total_tokens", 0)
            reply = result["choices"][0]
            if (
                result.get("local_protocol_error")
                or reply.get("finish_reason") != "stop"
                and (reply.get("finish_reason") != "tool_calls")
            ):
                raise ValueError("protocol_or_truncation")
            message = reply["message"]
            invoked = message.get("tool_calls") or []
            if not invoked:
                if reply.get("finish_reason") != "stop":
                    raise ValueError("protocol_or_truncation")
                text = message.get("content") or ""
                if not text.strip() or (
                    case.startswith("receipt") and (tools != 1 or receipt not in text)
                ):
                    raise ValueError("missing_grounded_answer")
                break
            if not case.startswith("receipt"):
                raise ValueError("unnecessary_tool")
            if tools or len(invoked) != 1:
                raise ValueError("repeated_tool")
            call = invoked[0]
            arguments = json.loads(call["function"]["arguments"])
            if (
                reply.get("finish_reason") != "tool_calls"
                or call["function"]["name"] != "read_receipt"
                or arguments != {"step": 1}
                or type(arguments.get("step")) is not int
            ):
                raise ValueError("wrong_tool_arguments")
            tools += 1
            body["messages"].extend(
                [
                    message,
                    {"role": "tool", "tool_call_id": call["id"], "content": receipt},
                ]
            )
            # Проверяем добровольное завершение, не принуждаем tool_choice=none.
            body["tool_choice"] = "auto"
        else:
            raise ValueError("round_cap")
    except Exception as error:
        failure = str(error) if type(error) is ValueError else "request_failed"
        if failure not in {
            "protocol_or_truncation",
            "missing_grounded_answer",
            "unnecessary_tool",
            "repeated_tool",
            "wrong_tool_arguments",
            "round_cap",
        }:
            failure = "request_failed"
    return {
        "case": case,
        "repeat": repeat,
        "passed": not failure,
        "failure": failure,
        "inferences": calls,
        "tools": tools,
        "tokens": tokens,
        "seconds": round(time.monotonic() - started, 3),
    }
