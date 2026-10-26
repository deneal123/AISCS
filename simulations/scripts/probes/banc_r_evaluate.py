"""Run the separately qualified R part after the Python job has terminated."""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inventory import REGISTRY, ROOT, load, save
from paths import PROFILES
from simctl import checked_work, command, phase


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run")
    args = parser.parse_args()
    run = checked_work(ROOT / args.run)
    registry = load(REGISTRY)
    row = next(x for x in registry["candidates"] if x["id"] == "SIM-011")
    result = load(run / "result.json")
    if result["commit"] != row["commit"] or result["status"] == "running":
        raise ValueError("Wrong source version or Python job not terminal")
    running = command(["docker", "ps", "--filter", "name=aspa-sim-sim-011-", "-q"])
    if running.returncode or running.stdout.strip():
        raise ValueError("A SIM-011 compute job is still running")
    profile = load(PROFILES)["SIM-011"]["r_profile"]
    (run / "home").mkdir(exist_ok=True)
    for name in ("banc_r_install.R", "banc_r_check.R"):
        shutil.copy2(Path(__file__).with_name(name), run / "probes" / name)
    evidence = {"commit": row["commit"], "profile": profile, "phases": []}
    for stage in ("install", "native_tests"):
        record = phase(row, profile, stage, run, registry["policy"])
        evidence["phases"].append(record)
        save(run / "r-result.json", evidence)
        print("BANC R", stage, record["status"], flush=True)
        # A failed dependency install permits only diagnosis of original startup;
        # a timeout/OOM/monitor failure stops this separate job.
        if record["status"] == "blocked":
            break
    save(run / "r-result.json", evidence)


if __name__ == "__main__":
    main()
