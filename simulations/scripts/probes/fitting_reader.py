"""Verify full-model exports without JAX/BrainX/NumPy or floating-point ID conversion."""

import argparse
import csv
import hashlib
import json
import math
import zipfile
from pathlib import Path

from flyvis_reader import read_array


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    run = Path(parser.parse_args().run).resolve()
    root = Path(__file__).resolve().parents[3]
    assert run.parent == root / "research/.work/simulator-evaluation/SIM-002"
    out = run / "exports"
    value = json.loads((out / "functional.json").read_text())
    assert value["status"] == "passed" and value["nodes"] == 127400
    primary = (
        root
        / "research/.work/simulator-evaluation/SIM-002/assets/author/Completeness_630_final.csv"
    )
    with primary.open(encoding="utf-8-sig", newline="") as stream:
        expected_ids = [row["id"] for row in csv.DictReader(stream)]
    assert len(expected_ids) == len(set(expected_ids)) == 127400
    cases = []
    signatures = {}
    for item in value["cases"]:
        path = out / item["file"]
        assert (
            path.parent == out
            and hashlib.sha256(path.read_bytes()).hexdigest() == item["file_sha256"]
        )
        with zipfile.ZipFile(path) as archive:
            states, shape, digest = read_array(archive, "voltage_mV")
            events, event_shape, event_digest = read_array(archive, "events")
            ids, _, _ = read_array(archive, "ids")
            times, _, _ = read_array(archive, "times_ms")
        assert shape == (50, 127400) and list(shape) == item["shape"]
        assert ids == expected_ids
        assert all(math.isfinite(x) for x in states)
        assert digest == item["state_sha256"] and event_digest == item["events_sha256"]
        assert event_shape == (item["events"], 2)
        assert all(
            0 <= events[i] < 50 and 0 <= events[i + 1] < 127400
            for i in range(0, len(events), 2)
        )
        assert all(abs(t - (i + 1) * 0.2) < 1e-12 for i, t in enumerate(times))
        signatures[item["name"]] = (digest, event_digest)
        cases.append(
            {"name": item["name"], "values": len(states), "events": item["events"]}
        )
    assert signatures["seed-1"] == signatures["seed-1-repeat"]
    assert signatures["seed-1-no-input"] != signatures["seed-1"]
    for seed in [2, 3]:
        assert signatures[f"seed-{seed}"] != signatures["seed-1"]
    receipt = {
        "status": "passed",
        "imports": "standard library only; no JAX/BrainX/NumPy",
        "ids_checked_as": "exact source CSV strings, never floats",
        "nodes": 127400,
        "checked": cases,
        "repeat_seed_equal": True,
        "no_input_differs": True,
        "time_convention": "post-update output at (tick+1)*0.2 ms; native model units, no empirical calibration",
    }
    (out / "independent-readback.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
