"""Только синтетические русские запросы; ограниченные ответы для ручной оценки."""

import argparse
import json
import os

from local_llm.service.domain.model import MODEL_ID
from local_llm.service.infrastructure.llama.transport import LlamaTransport

from .candidates import CANDIDATES, require_dev_candidate
from .comparison import SYSTEM, TOOL, sampling_body


def review(request):
    rows = []
    for case, prompt in (
        ("russian", "Привет!"),
        ("arithmetic", "Сколько будет 17 плюс 25? Ответь только числом."),
        ("json", "Верни только JSON без оформления: поле ok равно true, поле count равно 3."),
        ("context", "Как называется мой проект? Ответь только названием."),
    ):
        messages = [{"role": "system", "content": SYSTEM}]
        if case == "context":
            messages.extend(
                [
                    {"role": "user", "content": "Мой проект называется Мурка."},
                    {"role": "assistant", "content": "Запомнил название проекта: Мурка."},
                ]
            )
        messages.append({"role": "user", "content": prompt})
        result = request(
            {
                "model": MODEL_ID,
                "messages": messages,
                "tools": [TOOL],
                "tool_choice": "auto",
                "temperature": 0,
                "max_tokens": 128,
            }
        )
        reply = result["choices"][0]
        message = reply["message"]
        text = (message.get("content") or "").strip()
        passed = reply["finish_reason"] == "stop" and not message.get("tool_calls")
        if case == "russian":
            passed = passed and any("а" <= letter.lower() <= "я" for letter in text)
        elif case == "arithmetic":
            passed = passed and text == "42"
        elif case == "context":
            passed = passed and text == "Мурка"
        else:
            try:
                value = json.loads(text)
                passed = (
                    passed
                    and value == {"ok": True, "count": 3}
                    and value["ok"] is True
                    and type(value["count"]) is int
                )
            except ValueError:
                passed = False
        rows.append({"case": case, "passed": bool(passed), "synthetic_answer": text[:400]})
    return {"passed": all(row["passed"] for row in rows), "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", choices=CANDIDATES)
    parser.add_argument("--profile", choices=("deterministic", "precise"), default="deterministic")
    args = parser.parse_args()
    require_dev_candidate(args.candidate, os.environ)
    transport = LlamaTransport(os.environ["LOCAL_LLM_API_KEY"])
    transport("/health")
    result = review(
        lambda body: transport("/v1/chat/completions", sampling_body(body, args.profile))
    )
    print(
        json.dumps(
            {
                "candidate": args.candidate,
                "protocol": "native-diagnostic-only",
                "profile": args.profile,
                **result,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
