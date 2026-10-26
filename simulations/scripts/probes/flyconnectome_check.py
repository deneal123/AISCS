"""Recheck retained FlyConnectome exports and release the owned Linux runtime."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inventory import ROOT, WORK, load, save
from simctl import checked_work, phase


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument(
        "--runtime",
        type=Path,
        help="Adopt this run's already-owned diagnostic runtime, then release it",
    )
    args = parser.parse_args()
    run = checked_work(args.run)
    if run.parent != WORK / "SIM-026":
        raise ValueError("Expected an owned SIM-026 run")
    core = load(run / "result.json")
    core_hash = hashlib.sha256((run / "result.json").read_bytes()).hexdigest()
    if not core["environment_volume"].get("absent"):
        raise ValueError("Wait for the original run to finish")
    if subprocess.check_output(
        ["docker", "ps", "-q", "--filter", "label=aspa.simulation.owner=simctl"],
        text=True,
    ).strip():
        raise ValueError("Another owned computation is active")
    token = uuid.uuid4().hex[:10]
    folder = run / ("check-" + token)
    probes = folder / "probes"
    probes.mkdir(parents=True)
    for name in ["flyconnectome_reader.py", "flyconnectome_render.py"]:
        shutil.copyfile(Path(__file__).with_name(name), probes / name)
    adopted = None
    if args.runtime:
        path = checked_work(args.runtime)
        if path.parent.parent != run or path.name != "runtime.json":
            raise ValueError("Runtime must belong to this exact run")
        adopted = load(path)
        if adopted["core_result_sha256"] != core_hash or adopted["status"] not in {
            "ready",
            "diagnosing",
        }:
            raise ValueError("Runtime is stale or already released")
        volume = adopted["volume"]
    else:
        volume = "aspa-sim-sim-026-check-env-" + token
        subprocess.run(
            [
                "docker",
                "volume",
                "create",
                "--label",
                "aspa.simulation.owner=simctl",
                "--label",
                "aspa.simulation.id=SIM-026",
                volume,
            ],
            check=True,
            capture_output=True,
        )
    labels = json.loads(
        subprocess.check_output(["docker", "volume", "inspect", volume], text=True)
    )[0]["Labels"]
    if (
        labels.get("aspa.simulation.owner") != "simctl"
        or labels.get("aspa.simulation.id") != "SIM-026"
    ):
        raise ValueError("Refusing an unowned diagnostic volume")
    profile = dict(core["profile"], _environment_volume=volume)
    for name in ["install", "runtime_prefix"]:
        profile[name] = profile[name].replace(
            "/work/system-packages.txt", f"/work/{folder.name}/system-packages.txt"
        )
    profile["install"] = (
        profile["install"]
        .replace(
            "/work/dependencies.lock.txt", f"/work/{folder.name}/dependencies.lock.txt"
        )
        .replace(
            "/work/install-report.json", f"/work/{folder.name}/install-report.json"
        )
    )
    profile["runtime_prefix"] = profile["runtime_prefix"].replace(
        "build-essential ", ""
    )
    stages = [] if adopted else ["install"]
    for stage in ["reader", "render"]:
        name = "check_" + stage + "_" + token
        profile[name] = (
            f"ASPA_FLYCONNECTOME_REVIEW=/work/{folder.name}/exports /work/env/bin/python -u /work/{folder.name}/probes/flyconnectome_{stage}.py driver"
        )
        stages.append(name)
    report = {
        "status": "running",
        "phases": [],
        "core_result_sha256": core_hash,
        "scripts": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in probes.glob("*.py")
        },
        "environment_volume": {"name": volume},
        "adopted_runtime": args.runtime.as_posix() if args.runtime else None,
    }
    receipt = folder / "result.json"
    try:
        for stage in stages:
            print(stage, flush=True)
            item = phase({"id": "SIM-026"}, profile, stage, run, core["policy"])
            report["phases"].append(item)
            save(receipt, report)
            if item["status"] != "passed":
                break
        report["status"] = (
            "passed"
            if len(report["phases"]) == len(stages)
            and all(p["status"] == "passed" for p in report["phases"])
            else "failed"
        )
    finally:
        current = json.loads(
            subprocess.check_output(["docker", "volume", "inspect", volume], text=True)
        )[0]["Labels"]
        if (
            current.get("aspa.simulation.owner") != "simctl"
            or current.get("aspa.simulation.id") != "SIM-026"
        ):
            raise ValueError("Volume ownership changed")
        subprocess.run(
            ["docker", "volume", "rm", volume], check=True, capture_output=True
        )
        absent = subprocess.run(
            ["docker", "volume", "inspect", volume],
            capture_output=True,
            text=True,
            check=False,
        )
        report["environment_volume"]["absent"] = (
            absent.returncode != 0 and "no such volume" in absent.stderr.lower()
        )
        if hashlib.sha256((run / "result.json").read_bytes()).hexdigest() != core_hash:
            raise ValueError("Original run receipt changed")
        save(receipt, report)
        if adopted:
            adopted.update(
                status="released",
                volume_absent=report["environment_volume"]["absent"],
                release_receipt=receipt.relative_to(ROOT).as_posix(),
            )
            save(checked_work(args.runtime), adopted)
    print(receipt.relative_to(ROOT).as_posix(), report["status"], flush=True)
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
