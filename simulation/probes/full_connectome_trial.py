"""Prepare and probe the pinned full graph using the existing guarded runner."""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inventory import REGISTRY, ROOT, load, save
from simctl import phase


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-host-reserve", action="store_true")
    args = parser.parse_args()
    run = ROOT / "research/.work/simulator-evaluation/SIM-001/20261005T105111Z-6999dc"
    registry = load(REGISTRY)
    policy = dict(registry["policy"])
    if args.no_host_reserve:
        policy["host_reserve_bytes"] = 0
    row = next(x for x in registry["candidates"] if x["id"] == "SIM-001")
    profile = dict(load(ROOT / "simulation/profiles.json")["SIM-001"])
    source = run / "source/fly_arena/data.py"
    upstream = ROOT / row["path"] / "fly_arena/data.py"
    original = upstream.read_text(encoding="utf-8")
    # Only the isolated work copy changes; impose the agreed two-attempt limit.
    bounded = original.replace("range(4)", "range(2)").replace("if attempt == 3:", "if attempt == 1:")
    # Close writable maps before hashing on the Windows Docker bind mount.
    bounded = bounded.replace("    temp.unlink()\n    manifest = {", "    temp.unlink()\n    del posts, counts\n    manifest = {")
    if source.read_text(encoding="utf-8") not in (original, bounded):
        raise ValueError("Unexpected working-copy changes")
    source.write_text(bounded, encoding="utf-8", newline="\n")
    receipt = {
        "policy": policy,
        "commit": row["commit"],
        "upstream_sha256": hashlib.sha256(upstream.read_bytes()).hexdigest(),
        "working_copy_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "patch": "two download attempts; close writable maps before manifest hashing; upstream untouched",
        "phases": [],
    }
    receipt_path = run / "full-connectome-trial.json"
    if receipt_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        receipt_path.rename(run / ("full-connectome-trial-" + stamp + ".json"))
    save(receipt_path, receipt)
    profile.update(
        data_scope="full_male_cns_v1_graph",
        prepare="/work/env/bin/python -m fly_arena prepare --data /work/connectome",
        prepare_admission_bytes=512 * 1024**2,
        connectome="/work/env/bin/python -m fly_arena run --mode connectome --headless --gl egl --data /work/connectome --seconds 0.1 --seed 1 --output /work/exports/full-connectome-seed1 --video /work/exports/full-connectome-seed1.mp4",
        connectome_admission_bytes=1024**3,
    )
    try:
        for stage in ("prepare", "connectome"):
            result = phase(row, profile, stage, run, policy)
            receipt["phases"].append(result)
            save(run / "full-connectome-trial.json", receipt)
            print(json.dumps(result), flush=True)
            if result["status"] != "passed":
                break
    finally:
        source.write_bytes(upstream.read_bytes())


if __name__ == "__main__":
    main()
