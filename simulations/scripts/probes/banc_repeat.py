"""Repeat the BANC numerical scenario in a fresh process; retain the first run."""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inventory import REGISTRY, ROOT, load, save
from simctl import checked_work, command, phase


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run")
    args = parser.parse_args()
    run = checked_work(ROOT / args.run)
    registry = load(REGISTRY)
    row = next(x for x in registry["candidates"] if x["id"] == "SIM-011")
    active = command(["docker", "ps", "--filter", "name=aspa-sim-sim-011-", "-q"])
    if active.returncode or active.stdout.strip():
        raise ValueError("A SIM-011 compute process is still running")
    if not (run / "env").is_dir():
        raise ValueError("Replay environment was cleaned; create a new run")
    profile = load(run / "result.json")["profile"]
    image = command(["docker", "image", "inspect", profile["image"]])
    expected = load(run / "runtime-images.json")["images"][profile["image"]]["Id"]
    if image.returncode or json.loads(image.stdout)[0]["Id"] != expected:
        raise ValueError("Replay image differs from the first process")
    reference = row["frozen_inputs"]
    if digest(ROOT / reference["path"]) != reference["sha256"]:
        raise ValueError("Frozen BANC manifest changed")
    for name in ("banc_probe.py",):
        shutil.copy2(Path(__file__).with_name(name), run / "probes" / name)
    profile["functional"] = (
        "ASPA_BANC_EXPORT_DIR=replay-export /work/env/bin/python /work/probes/banc_probe.py full"
    )
    evidence = {"phase": phase(row, profile, "functional", run, registry["policy"])}
    if evidence["phase"]["status"] == "passed":
        comparisons = {}
        for name in (
            "active-by-step.csv",
            "activation-by-neuron.csv",
            "banc-cascade.png",
        ):
            first, second = run / "export" / name, run / "replay-export" / name
            comparisons[name] = {
                "first_sha256": digest(first),
                "replay_sha256": digest(second),
            }
            comparisons[name]["equal"] = (
                comparisons[name]["first_sha256"] == comparisons[name]["replay_sha256"]
            )
        evidence["comparisons"] = comparisons
        evidence["repeat_content_equal"] = all(x["equal"] for x in comparisons.values())
        evidence["status"] = "passed" if evidence["repeat_content_equal"] else "failed"
    else:
        evidence["status"] = evidence["phase"]["status"]
    save(run / "replay-result.json", evidence)
    print("BANC independent replay", evidence["status"], flush=True)


if __name__ == "__main__":
    main()
