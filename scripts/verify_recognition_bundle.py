"""Independent bookkeeping and signal/feature checks for the frozen CNS bundle."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from service.contracts import SimulationConfig
from service.domain.connectome_signals import FEATURES, features
from service.infrastructure.recognition.connectome_identity import numerical_identity


def verify(bundle: Path, signals: Path | None = None) -> dict:
    def read(name):
        return json.loads((bundle / name).read_text(encoding="utf-8"))
    candidate, frozen, model, registry = (
        read(name)
        for name in ("candidate.json", "frozen.json", "classifier.json", "dataset-registry.json")
    )
    assert (
        hashlib.sha256((bundle / "candidate.json").read_bytes()).hexdigest()
        == frozen["candidate_sha256"]
    )
    assert (
        hashlib.sha256((bundle / "protocol.json").read_bytes()).hexdigest()
        == frozen["binding"]["protocol_sha256"]
    )
    assert all(model[key] == value for key, value in candidate.items())
    assert registry["numerical_identity"] == numerical_identity()
    assert candidate["binding"] == frozen["binding"]
    assert registry["protocol_sha256"] == frozen["binding"]["protocol_sha256"]
    rows, groups = registry["records"], defaultdict(list)
    assert len(rows) == 480 and len({row["id"] for row in rows}) == 480
    raw_checked = 0
    for row in rows:
        config = SimulationConfig.model_validate(row["configuration"])
        assert config.digest() == row["configuration_sha256"]
        assert row["label"] == config.stimulus and row["region"] == config.stimulus_region
        assert len(row["features"]) == len(FEATURES) and np.isfinite(row["features"]).all()
        groups[row["group"]].append(row)
        if signals is not None:
            import pyarrow.parquet as pq

            path = signals / (row["id"] + ".parquet")
            assert hashlib.sha256(path.read_bytes()).hexdigest() == row["signal_sha256"]
            table = pq.read_table(path)
            np.testing.assert_array_equal(
                features(table["time_ms"].to_numpy(), table["signal_uv"].to_numpy()),
                row["features"],
            )
            raw_checked += 1
    seeds = set()
    for items in groups.values():
        assert len(items) == 3 and {row["label"] for row in items} == {"none", "weak", "strong"}
        assert len({row["partition"] for row in items}) == 1
        configs = [
            {k: v for k, v in row["configuration"].items() if k != "stimulus"} for row in items
        ]
        assert configs[0] == configs[1] == configs[2]
        seed = configs[0]["seed"]
        assert seed not in seeds
        seeds.add(seed)
    assert len(groups) == 160
    assert Counter(row["partition"] for row in rows) == {"train": 288, "validation": 96, "test": 96}
    classes, matrix = model["evaluation"]["classes"], np.zeros((3, 3), dtype=int)
    tested = 0
    for row in rows:
        if row["partition"] != "test":
            continue
        weights = model["models"][row["region"]]
        x = (np.array(row["features"]) - weights["mean"]) / weights["scale"]
        scores = np.array(weights["coefficients"]) @ x + weights["intercepts"]
        guessed = weights["classes"][int(np.argmax(scores))]
        assert guessed == row["prediction"]
        matrix[classes.index(row["label"]), classes.index(guessed)] += 1
        tested += 1
    assert tested == 96 and matrix.tolist() == model["evaluation"]["confusion_matrix"]
    score = float(np.mean(matrix.diagonal() / matrix.sum(axis=1)))
    assert score == model["evaluation"]["test_balanced_accuracy"]
    return {
        "passed": True,
        "records": len(rows),
        "groups": len(groups),
        "partition_overlap": 0,
        "raw_signals_verified": raw_checked,
        "heldout_predictions_verified": tested,
        "candidate_unchanged_after_test": True,
        "confusion_matrix": matrix.tolist(),
        "balanced_accuracy": score,
        "scope": "Frozen synthetic model bookkeeping; not biological validation",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--signals", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.bundle, args.signals)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
