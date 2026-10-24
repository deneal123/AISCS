"""Контроль нативного протокола того же llama-server, без изменения gateway продукта."""

import argparse
import json
import os

from local_llm.service.infrastructure.llama.transport import LlamaTransport

from .candidates import CANDIDATES, require_dev_candidate
from .comparison import exercise, exercise_history, sampling_body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", choices=CANDIDATES)
    parser.add_argument("--repeats", type=int, default=1, choices=range(1, 11))
    parser.add_argument(
        "--profile",
        choices=("deterministic", "qwen3-nonthinking", "qwen35-text", "precise"),
        default="deterministic",
    )
    parser.add_argument("--history-rounds", type=int, default=0, choices=range(17))
    args = parser.parse_args()
    require_dev_candidate(args.candidate, os.environ)
    transport = LlamaTransport(os.environ["LOCAL_LLM_API_KEY"])
    transport("/health")

    def request(body):
        return transport("/v1/chat/completions", sampling_body(body, args.profile))

    result = exercise(
        request,
        repeats=args.repeats,
        on_case=lambda row: print(json.dumps(row), flush=True),
    )
    if args.history_rounds and result["passed"]:
        result["history"] = exercise_history(
            request,
            rounds=args.history_rounds,
            on_step=lambda row: print(json.dumps(row), flush=True),
        )
        result["passed"] = result["history"]["passed"]
    print(
        json.dumps(
            {
                "candidate": args.candidate,
                "protocol": "native-diagnostic-only",
                "profile": args.profile,
                "revision": CANDIDATES[args.candidate].revision,
                **result,
            }
        ),
        flush=True,
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
