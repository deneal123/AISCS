"""Проверить CPU API из существующей сети agents, без перезапуска сервисов."""

import argparse
import json
import runpy
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
entries = runpy.run_path(str(ROOT / "docker/sync_env.py"))["entries"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=1, choices=range(1, 17))
    parser.add_argument(
        "--choice", choices=("required", "auto", "named"), default="required"
    )
    parser.add_argument(
        "--suite", choices=("arithmetic", "opaque"), default="arithmetic"
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--provider", action="store_true")
    modes.add_argument("--refinement", action="store_true")
    modes.add_argument("--admission", action="store_true")
    parser.add_argument(
        "--admission-profile",
        choices=(
            "baseline",
            "concise",
            "guided",
            "workflow_guided",
            "ordered",
            "decision_first",
            "both",
            "all",
        ),
        default="both",
    )
    parser.add_argument(
        "--admission-suite", choices=("basic", "extended"), default="basic"
    )
    parser.add_argument(
        "--admission-sampling", choices=("diagnostic", "runtime"), default="diagnostic"
    )
    args = parser.parse_args()
    if args.admission_suite != "basic" and not args.admission:
        parser.error("Расширенный корпус доступен только с --admission")
    if args.admission_sampling != "diagnostic" and not args.admission:
        parser.error("Параметры admission доступны только с --admission")
    values = entries((ROOT / "docker/.env.dev").read_text(encoding="utf-8"))
    key = values.get("LOCAL_LLM_API_KEY", "")
    if len(key) < 32:
        raise SystemExit("local_llm_key_unavailable")
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "gpthub-dev-agents-1",
            "python",
            "-c",
            (
                ROOT
                / (
                    "local_llm/scripts/acceptance/provider.py"
                    if args.provider
                    else "local_llm/scripts/acceptance/admission.py"
                    if args.admission
                    else "local_llm/scripts/acceptance/refinement.py"
                    if args.refinement
                    else "local_llm/scripts/acceptance/tool_calling.py"
                )
            ).read_text(encoding="utf-8"),
        ],
        check=False,
        input=json.dumps(
            {
                "key": key,
                "base_url": "http://local-llm:8080",
                "rounds": args.rounds,
                "choice": args.choice,
                "suite": args.suite,
                "admission_profile": args.admission_profile,
                "admission_suite": args.admission_suite,
                "admission_sampling": args.admission_sampling,
            }
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=120 + args.rounds * 240,
    )
    # stderr может содержать внешнюю диагностику; наружу выходит только JSON протокол.
    try:
        outcome = json.loads(result.stdout)
    except ValueError:
        outcome = {"failure": "probe_protocol_invalid"}
    print(json.dumps(outcome), flush=True)
    return result.returncode or (1 if "failure" in outcome else 0)


if __name__ == "__main__":
    raise SystemExit(main())
