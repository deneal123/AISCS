"""Временный dev A/B: прежний gateway/runtime, меняются только проверенные веса."""

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from local_llm.service.configuration import configuration
from local_llm.service.infrastructure.llama.runtime import run
from local_llm.service.infrastructure.llama.transport import LlamaTransport
from local_llm.service.infrastructure.models.artifacts import download, verified
from local_llm.service.presentation.http import Gateway

from .candidates import CANDIDATES, artifact_for, require_dev_candidate
from .comparison import exercise, sampling_body


def serve(name):
    settings = configuration(os.environ)
    artifact = artifact_for(name)
    limit = Path("/sys/fs/cgroup/memory.max")
    if limit.exists():
        value = limit.read_text().strip()
        if value != "max" and CANDIDATES[name].memory_bytes > int(value):
            raise ValueError("comparison_memory_policy_blocked")
    path = settings.model_path.parent / artifact.filename
    if not verified(path, artifact):
        raise ValueError("comparison_model_unverified")
    command = list(settings.command)
    command[command.index("--model") + 1] = str(path)
    if name in {"qwen3", "qwen35", "qwen35-2b"}:
        # Штатный non-thinking режим Qwen; иначе короткий ответ тратится на размышление.
        command[command.index("--top-k") + 1] = "20"
        command[command.index("--repeat-penalty") + 1] = "1.0"
        command.extend(
            [
                "--chat-template-kwargs",
                '{"enable_thinking":false}',
                "--reasoning",
                "off",
                "--min-p",
                "0",
            ]
        )
    settings = replace(settings, model_path=path, command=tuple(command))
    # Alias сохранён только ради неизменного контракта agents при A/B.
    # Фактические веса и ревизия всегда указаны в отдельном отчёте сравнения.
    server = Gateway(
        settings.address,
        settings.api_key,
        upstream=LlamaTransport(settings.api_key, request_timeout=settings.request_timeout_sec),
    )
    print(json.dumps({"candidate": name, "revision": CANDIDATES[name].revision}), flush=True)
    return run(server, settings.command, settings.child_environment)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "serve", "probe"))
    parser.add_argument("candidate", choices=CANDIDATES)
    parser.add_argument(
        "--profile",
        choices=("deterministic", "qwen3-nonthinking", "qwen35-text"),
        default="deterministic",
    )
    parser.add_argument("--repeats", type=int, default=3, choices=range(1, 11))
    args = parser.parse_args()
    require_dev_candidate(args.candidate, os.environ)
    if args.action == "prepare":
        download(artifact_for(args.candidate), Path("/models"), timeout=1800)
        print(json.dumps({"candidate": args.candidate, "prepared": True}))
        return 0
    if args.action == "serve":
        return serve(args.candidate)
    # Используем настоящий HTTP gateway: аутентификацию, compiler и normalizer.
    import urllib.request

    key = os.environ["LOCAL_LLM_API_KEY"]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    # Не записываем неготовый runtime как неудачу качества на всём корпусе.
    with opener.open("http://127.0.0.1:8080/health", timeout=5) as response:
        if response.status != 200:
            raise ValueError("comparison_runtime_not_ready")

    def request(body):
        body = sampling_body(body, args.profile)
        req = urllib.request.Request(
            "http://127.0.0.1:8080/v1/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        with opener.open(req, timeout=125) as response:
            return json.load(response)

    result = exercise(
        request, repeats=args.repeats, on_case=lambda row: print(json.dumps(row), flush=True)
    )
    print(
        json.dumps(
            {
                "candidate": args.candidate,
                "revision": CANDIDATES[args.candidate].revision,
                "runtime": "b11846",
                "protocol": "native-tools-v1",
                "profile": args.profile,
                **result,
            }
        ),
        flush=True,
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
