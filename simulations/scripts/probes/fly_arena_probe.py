"""Headless body-only trials; compare numerical exports, excluding wall time."""

import csv
import hashlib
import json
import math
import subprocess
import sys
import uuid
from itertools import pairwise
from pathlib import Path

exports = Path("/work/exports") / ("body-" + uuid.uuid4().hex[:8])
exports.mkdir(parents=True, exist_ok=False)
neural_fields = {
    "retina_spikes",
    "DNp09_L_Hz",
    "DNp09_R_Hz",
    "DNa02_L_Hz",
    "DNa02_R_Hz",
}
results = []
for label, seed in [("seed1", 1), ("seed2", 2), ("seed3", 3), ("seed1-repeat", 1)]:
    folder = exports / label
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fly_arena",
            "run",
            "--mode",
            "body-demo",
            "--headless",
            "--gl",
            "egl",
            "--seconds",
            "3",
            "--seed",
            str(seed),
            "--output",
            str(folder),
        ],
        check=True,
    )
    csv_files, metadata_files = list(folder.glob("*.csv")), list(folder.glob("*.json"))
    assert len(csv_files) == len(metadata_files) == 1
    metadata = json.loads(metadata_files[0].read_text("utf-8"))
    assert not metadata["error"] and not metadata["interrupted"]
    assert metadata["graph"] is None and metadata["brain_config"] is None
    assert metadata["simulation_seconds"] >= 3
    with csv_files[0].open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert rows and len(rows[0]) == 16
    assert all(row[k] == "" for row in rows for k in neural_fields)
    assert all(
        math.isfinite(float(v))
        for row in rows
        for k, v in row.items()
        if k not in neural_fields
    )
    assert metadata["total_spikes"] == 0 and all(
        float(row["spikes"]) == 0 for row in rows
    )
    times = [float(row["time_s"]) for row in rows]
    assert all(b > a for a, b in pairwise(times))
    numerical = [
        {
            k: None if k in neural_fields else float(v)
            for k, v in row.items()
            if k != "wall_s"
        }
        for row in rows
    ]
    digest = hashlib.sha256(json.dumps(numerical, sort_keys=True).encode()).hexdigest()
    results.append(
        {
            "seed": seed,
            "trial": label,
            "rows": len(rows),
            "numerical_sha256": digest,
            "simulation_seconds": times[-1],
            "wall_seconds": metadata["wall_seconds"],
            "columns": list(rows[0]),
        }
    )
assert results[0]["numerical_sha256"] == results[3]["numerical_sha256"], (
    "Repeated seed differs"
)
(exports / "body-trials.json").write_text(
    json.dumps(
        {
            "scope": "body_demo_without_connectome",
            "repeat_seed_equal": True,
            "trials": results,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(
    json.dumps(
        {
            "trials": len(results),
            "repeat_seed_equal": True,
            "exports": str(exports),
            "absent_neural_fields": sorted(neural_fields),
        }
    )
)
