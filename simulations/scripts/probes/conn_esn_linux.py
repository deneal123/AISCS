"""Retry the exact Julia project with a disposable Linux-local package depot.

Windows bind IO was measured separately. Primary inputs and receipts stay in
the designated work area; the dependency layer is removed with its container.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inventory import REGISTRY, ROOT, WORK, load, save
from paths import PROFILES
from simctl import (
    checked_work,
    command,
    copy_checkout,
    docker_memory,
    probe_fingerprint,
)


def remove_owned_container(name):
    """Reconcile even an uncertain launch without touching another runtime."""
    if not name.startswith("aspa-sim-sim-013-linux-"):
        raise ValueError("Not a SIM-013 owned runtime")
    inspected = command(["docker", "inspect", name], timeout=15)
    if inspected.returncode:
        # A daemon/transport error does not establish that the container is gone.
        missing = (
            "no such object" in inspected.stderr.lower()
            or "no such container" in inspected.stderr.lower()
        )
        return {
            "container_absent": missing,
            "container_cleanup_observation": inspected.stderr.strip(),
        }
    info = json.loads(inspected.stdout)
    if (
        len(info) != 1
        or info[0].get("Name") != "/" + name
        or info[0].get("Config", {}).get("Labels", {}).get("aspa.simulation.owner")
        != "simctl"
    ):
        raise ValueError("Container ownership could not be verified")
    removed = command(["docker", "rm", "-f", name], timeout=30)
    after = command(["docker", "inspect", name], timeout=15)
    missing = after.returncode != 0 and (
        "no such object" in after.stderr.lower()
        or "no such container" in after.stderr.lower()
    )
    return {
        "container_removal_exit_code": removed.returncode,
        "container_absent": missing,
    }


def run_phase(name, stage, text, run, policy):
    log = run / ("linux-" + stage + "-" + uuid.uuid4().hex[:8] + ".log")
    args = ["docker", "exec", "-w", "/work/source", name, "sh", "-ec", text]
    record = {
        "stage": stage,
        "command": text,
        "docker_command": args,
        "log": log.name,
        "memory_scope": "cumulative peak of retained Linux container",
        "peak_memory_bytes": 0,
        "probe_fingerprint": probe_fingerprint(text, run / "probes"),
    }
    deadline = (
        policy["install_seconds"]
        if stage == "install"
        else policy["smoke_seconds"]
        if stage == "smoke"
        else policy["functional_seconds"]
    )
    started = time.monotonic()
    with log.open("w", encoding="utf-8", newline="\n") as stream:
        process = subprocess.Popen(args, stdout=stream, stderr=subprocess.STDOUT)
        while process.poll() is None:
            if time.monotonic() - started >= deadline:
                stopped = command(["docker", "rm", "-f", name], timeout=30)
                record.update(
                    status="blocked",
                    reason="timeout",
                    termination_confirmed=stopped.returncode == 0,
                )
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                break
            peak = docker_memory(name)
            if peak is not None:
                record["peak_memory_bytes"] = max(record["peak_memory_bytes"], peak)
            else:
                record["memory_observation_failures"] = (
                    record.get("memory_observation_failures", 0) + 1
                )
            time.sleep(1)
    record.update(
        seconds=round(time.monotonic() - started, 3),
        exit_code=process.returncode,
        log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
    )
    record.setdefault("status", "passed" if process.returncode == 0 else "failed")
    return record


def retain_for_diagnosis(requested, result):
    return bool(
        requested
        and result.get("status") == "partial"
        and not any(p.get("reason") == "timeout" for p in result.get("phases", []))
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "run",
        nargs="?",
        help="Existing pinned checkpoint; omitted creates a fresh isolated run",
    )
    parser.add_argument(
        "--cache-from", help="Prior SIM-013 run whose disposable depot may be read"
    )
    parser.add_argument(
        "--keep-runtime-on-failure",
        action="store_true",
        help="Keep an idle owned partial-trial runtime for same-SIM diagnosis; explicitly clean it before the next SIM",
    )
    args = parser.parse_args()
    registry = load(REGISTRY)
    row = next(x for x in registry["candidates"] if x["id"] == "SIM-013")
    profile = load(PROFILES)["SIM-013"]
    policy = registry["policy"]
    cache = None
    if args.cache_from:
        prior = checked_work(ROOT / args.cache_from)
        if prior.parent != WORK / "SIM-013":
            raise ValueError("Dependency cache belongs to another SIM")
        cache = checked_work(prior / "home/.julia")
        if not (cache / "packages").is_dir():
            raise ValueError("Prior disposable package cache is unavailable")
    if args.run:
        run = checked_work(ROOT / args.run)
        if run.parent != WORK / "SIM-013":
            raise ValueError("Checkpoint belongs to another SIM")
    else:
        run = checked_work(
            WORK
            / "SIM-013"
            / (
                time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
                + "-"
                + uuid.uuid4().hex[:6]
            )
        )
        run.mkdir(parents=True)
        copy_checkout(row, run / "source")
        from probes.conn_esn_assets import hydrate

        hydrate(run)
    for relative, digest in load(ROOT / row["source_inventory"])["files"].items():
        if (
            hashlib.sha256((run / "source" / relative).read_bytes()).hexdigest()
            != digest
        ):
            raise ValueError("Pinned source was modified: " + relative)
    active = command(["docker", "ps", "--filter", "name=aspa-sim-sim-013-", "-q"])
    if active.returncode or active.stdout.strip():
        raise ValueError("A SIM-013 process is already running")
    if shutil.disk_usage(WORK).free < policy["disk_reserve_bytes"]:
        raise ValueError("Insufficient disk reserve for cache transport")
    for folder in ["tmp", "home", "probes"]:
        (run / folder).mkdir(exist_ok=True)
    shutil.copytree(Path(__file__).parent, run / "probes", dirs_exist_ok=True)
    name = "aspa-sim-sim-013-linux-" + uuid.uuid4().hex[:10]
    result = {
        "repository": row["repository"],
        "commit": row["commit"],
        "run": run.relative_to(ROOT).as_posix(),
        "profile": profile,
        "policy": policy,
        "backend": "disposable Linux-local Julia depot",
        "container": name,
        "status": "running",
        "phases": [],
        "biological_validation": False,
        "keep_runtime_on_failure_requested": args.keep_runtime_on_failure,
    }
    output = run / "linux-runtime-result.json"
    if output.exists():
        raise ValueError(
            "Keep prior runtime evidence; create a fresh run for another attempt"
        )
    save(output, result)
    start = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--label",
        "aspa.simulation.owner=simctl",
        "--cpus",
        str(policy["cpu_threads"]),
        "--pids-limit",
        "256",
        "-v",
        str(run) + ":/work",
        "-w",
        "/work/source",
    ]
    if cache:
        start += ["-v", str(cache) + ":/cache:ro"]
        result["cache_from"] = cache.relative_to(ROOT).as_posix()
    for value in [
        "JULIA_DEPOT_PATH=/opt/aspa-julia",
        "JULIA_NUM_THREADS=4",
        "JULIA_NUM_PRECOMPILE_TASKS=1",
        "JULIA_PKG_PRECOMPILE_AUTO=0",
        "GKSwstype=100",
        "HOME=/work/home",
        "TMPDIR=/work/tmp",
        "OMP_NUM_THREADS=4",
        "OPENBLAS_NUM_THREADS=4",
        "MKL_NUM_THREADS=4",
        "CUDA_VISIBLE_DEVICES=",
    ]:
        start += ["-e", value]
    start += [profile["image"], "sleep", "infinity"]
    launch_attempted = False
    try:
        launch_attempted = True
        launched = command(start, timeout=120)
        if launched.returncode:
            raise RuntimeError("Owned container could not start: " + launched.stderr)
        result["docker_start"] = start
        installed = (
            "mkdir -p /opt/aspa-julia; "
            "cache=/work/home/.julia; if test -d /cache/packages; then cache=/cache; fi; "
            'if test -d "$cache/packages"; then '
            "tar --exclude='./compiled' --exclude='./logs' --exclude='./artifacts/jl_*' "
            '-cf /work/tmp/julia-depot-transfer.tar -C "$cache" .; '
            "sha256sum /work/tmp/julia-depot-transfer.tar > /work/depot-transfer.sha256; "
            "tar -xf /work/tmp/julia-depot-transfer.tar -C /opt/aspa-julia; "
            "rm /work/tmp/julia-depot-transfer.tar; fi; " + profile["install"]
        )
        stages = [
            ("install", installed),
            ("native_tests", profile["native_tests"]),
            ("smoke", profile["smoke"]),
            ("functional", profile["functional"]),
        ]
        if profile.get("native_repl"):
            stages.append(("native_repl", profile["native_repl"]))
        for stage, text in stages:
            record = run_phase(name, stage, text, run, policy)
            result["phases"].append(record)
            save(output, result)
            print("Linux depot", stage, record["status"], flush=True)
            if record["status"] != "passed" and not (
                stage == "native_tests"
                and record["status"] == "failed"
                and profile.get("diagnose_after_native_failure")
            ):
                break
        result["status"] = (
            "passed"
            if len(result["phases"]) == len(stages)
            and all(p["status"] == "passed" for p in result["phases"])
            else "partial"
            if any(p["status"] == "passed" for p in result["phases"])
            else "blocked"
        )
    except Exception as exc:
        result.update(status="blocked", controller_error=str(exc))
        raise
    finally:
        if retain_for_diagnosis(args.keep_runtime_on_failure, result):
            result.update(container_retained_for_diagnosis=True, container_absent=False)
        elif launch_attempted:
            try:
                result.update(remove_owned_container(name))
            except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
                result.update(container_absent=False, container_cleanup_error=str(exc))
        save(output, result)
        current = load(REGISTRY)
        target = next(x for x in current["candidates"] if x["id"] == "SIM-013")
        target["evaluation"] = {
            "status": result["status"],
            "result": output.relative_to(ROOT).as_posix(),
            "data_scope": profile["data_scope"],
            "phases": result["phases"],
        }
        target["cleanup"] = {
            "status": "pending",
            "reason": "linux_runtime_trial_requires_cleanup",
        }
        save(REGISTRY, current)
    print("SIM-013 Linux runtime", result["status"], flush=True)


if __name__ == "__main__":
    main()
