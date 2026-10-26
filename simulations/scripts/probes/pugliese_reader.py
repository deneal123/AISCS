"""Independent read-back of rate exports, without importing JAX or the source model."""

import csv
import hashlib
import json
from pathlib import Path

import numpy as np


def main():
    out = Path("/work/exports")
    result = json.loads((out / "functional.json").read_text())
    annotation = (
        Path.cwd()
        / "data/manc t1 connectome data/wTable_20250813_DNtoMN_unsorted_withModules.csv"
    )
    with annotation.open(newline="") as stream:
        ids = np.array([int(row["bodyId"]) for row in csv.DictReader(stream)])
    records = []
    for item in result["cases"]:
        path = out / item["export"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        with np.load(path, allow_pickle=False) as archive:
            rates, times, body_ids = (
                archive[key] for key in ["rates", "times", "body_ids"]
            )
        assert rates.shape == (4604, 2001)
        assert rates.dtype == np.float32
        assert np.isfinite(rates).all() and ((rates >= 0) & (rates <= 1000)).all()
        np.testing.assert_array_equal(body_ids, ids)
        assert times[0] == 0 and times[-1] == 2 and (np.diff(times) > 0).all()
        assert hashlib.sha256(rates.tobytes()).hexdigest() == item["array_sha256"]
        assert int(np.any(rates > 0.01, axis=1).sum()) == item["active_neurons"]
        records.append(
            {"file": path.name, "checked_values": int(rates.size), "body_ids": len(ids)}
        )
    first = np.load(out / "baseline-seed-1.npz")["rates"]
    repeat = np.load(out / "baseline-seed-1-repeat.npz")["rates"]
    np.testing.assert_array_equal(first, repeat)
    for seed in [2, 3]:
        assert not np.array_equal(
            first, np.load(out / f"baseline-seed-{seed}.npz")["rates"]
        )
    assert not np.any(np.load(out / "no-input.npz")["rates"])
    value = {
        "status": "passed",
        "project_imports": False,
        "jax_imports": False,
        "records": records,
        "repeat_exact": True,
        "different_parameter_seeds_differ": True,
    }
    (out / "independent-readback.json").write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(value), flush=True)


if __name__ == "__main__":
    main()
