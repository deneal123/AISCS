"""Проверка родного tools API llama.cpp без исполнения предложенных моделью действий."""

import json
import os
import time

from local_llm.service.domain.model import MODEL_ID
from local_llm.service.infrastructure.llama.transport import LlamaTransport


def exercise():
    upstream = LlamaTransport(os.environ["LOCAL_LLM_API_KEY"])
    properties = upstream("/props")
    template = properties["chat_template"]
    params = properties.get("default_generation_settings", {}).get("params", {})
    print(
        json.dumps(
            {
                "template_renders_tool_calls": "tool_calls" in template,
                "defaults": {
                    key: params.get(key) for key in ("temperature", "top_k", "repeat_penalty")
                },
            }
        ),
        flush=True,
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": "Прочитать веб-страницу по данной пользователем ссылке.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                    "additionalProperties": False,
                },
            },
        }
    ]
    for text in ("привет", "Прочитай https://example.com/ и перескажи страницу."):
        started = time.monotonic()
        result = upstream(
            "/v1/chat/completions",
            {
                "model": MODEL_ID,
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты — помощник. Отвечай кратко на русском языке.",
                    },
                    {"role": "user", "content": text},
                ],
                "tools": tools,
                "tool_choice": "auto",
                "temperature": 0.1,
                "max_tokens": 128,
                "stream": False,
            },
        )
        print(
            json.dumps(
                {
                    "case": text,
                    "seconds": round(time.monotonic() - started, 2),
                    "choice": result["choices"][0],
                    "usage": result.get("usage"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


if __name__ == "__main__":
    exercise()
