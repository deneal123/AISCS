"""Two-phase, resumable signal-only evaluation with a frozen pre-test candidate."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from service.contracts import SimulationConfig
from service.domain.catalog import catalog
from service.domain.connectome_signals import FEATURES, VERSION, features
from service.domain.recording_noise import add_noise
from service.shared.json_io import write_json


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value) -> None:
    pending = path.with_suffix(path.suffix + ".pending")
    write_json(pending, value)
    os.replace(pending, path)


def read_protocol(path: Path) -> dict:
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if (
        protocol["preset"] != "male-cns-hybrid-v1"
        or protocol["features_version"] != VERSION
        or protocol["classes"] != ["none", "weak", "strong"]
        or sum(protocol["split_groups_per_region"].values()) != protocol["groups_per_region"]
        or not 3 <= protocol["groups_per_region"] < 1000
        or any(
            protocol["split_groups_per_region"].get(name, 0) < 1
            for name in ("train", "validation", "test")
        )
    ):
        raise ValueError("Unsupported or incomplete recognition protocol")
    return protocol


def cases(protocol: dict) -> list[dict]:
    rng = np.random.default_rng(protocol["design_seed"])
    assignments = np.concatenate(
        [np.repeat(name, count) for name, count in protocol["split_groups_per_region"].items()]
    )
    base = catalog()["models"][1]["defaults"]
    result = []
    for region_index, region in enumerate(protocol["regions"]):
        split = rng.permutation(assignments)
        for group, partition in enumerate(split):
            cfg = {
                **base,
                "stimulus_region": region,
                "seed": protocol["seed_base"] + region_index * 1000 + group,
            }
            placement = json.loads(json.dumps(base["placement"]))
            for field, (low, high) in protocol["ranges"].items():
                value = float(rng.uniform(low, high))
                if field.startswith("electrode_"):
                    placement["electrode"][field.removeprefix("electrode_")] = value
                else:
                    cfg[field] = value
            cfg["placement"] = placement
            cfg.update(
                {
                    name: protocol["fixed"][name]
                    for name in ("duration_ms", "dt_ms", "conductivity_s_m")
                }
            )
            cfg["placement"]["reference"] = dict(
                zip(("x_um", "y_um", "z_um"), protocol["fixed"]["reference_um"], strict=True)
            )
            for label in protocol["classes"]:
                config = SimulationConfig.model_validate({**cfg, "stimulus": label})
                result.append(
                    {
                        "id": f"{region}-{group:02d}-{label}",
                        "group": f"{region}-{group:02d}",
                        "region": region,
                        "partition": str(partition),
                        "label": label,
                        "configuration": config.model_dump(mode="json"),
                        "configuration_sha256": config.digest(),
                    }
                )
    return result


def linear_predictions(x: np.ndarray, model: dict) -> np.ndarray:
    values = (x - np.asarray(model["mean"])) / np.asarray(model["scale"])
    scores = values @ np.asarray(model["coefficients"]).T + np.asarray(model["intercepts"])
    return np.asarray(model["classes"])[np.argmax(scores, axis=1)]


def fit_candidate(records: list[dict], regularizations: list[float]) -> tuple[dict, dict]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import balanced_accuracy_score
    from sklearn.preprocessing import StandardScaler

    train = [row for row in records if row["partition"] == "train"]
    validation = [row for row in records if row["partition"] == "validation"]
    x, y = (
        np.asarray([row["features"] for row in train]),
        np.asarray([row["label"] for row in train]),
    )
    vx, vy = (
        np.asarray([row["features"] for row in validation]),
        np.asarray([row["label"] for row in validation]),
    )
    scaler = StandardScaler().fit(x)
    best, score = None, -1.0
    for regularization in regularizations:
        candidate = LogisticRegression(C=regularization, max_iter=2000, random_state=7)
        candidate.fit(scaler.transform(x), y)
        value = float(balanced_accuracy_score(vy, candidate.predict(scaler.transform(vx))))
        if value > score:
            best, score = candidate, value
    model = {
        "feature_names": FEATURES,
        "classes": best.classes_.tolist(),
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "coefficients": best.coef_.tolist(),
        "intercepts": best.intercept_.tolist(),
        "C": float(best.C),
    }
    return model, {
        "validation_balanced_accuracy": score,
        "train_realizations": len(train),
        "validation_realizations": len(validation),
        "selected_C_on_validation": model["C"],
    }


def summary(records: list[dict], predictions, classes: list[str]) -> dict:
    from sklearn.metrics import balanced_accuracy_score, confusion_matrix

    labels = [row["label"] for row in records]
    matrix = confusion_matrix(labels, predictions, labels=classes)
    return {
        "test_balanced_accuracy": float(balanced_accuracy_score(labels, predictions)),
        "classes": classes,
        "confusion_matrix": matrix.tolist(),
        "test_realizations": len(records),
        "test_groups": len({row["group"] for row in records}),
        "recall_by_class": {
            name: float(matrix[i, i] / matrix[i].sum()) for i, name in enumerate(classes)
        },
        "majority_baseline_balanced_accuracy": 1 / 3,
    }


def evaluate_connectome(
    directory: Path,
    protocol_path: Path,
    phase: str,
    engine,
    recorder,
    identity: dict,
    progress=print,
) -> dict:
    protocol = read_protocol(protocol_path)
    directory.mkdir(parents=True, exist_ok=True)
    registry = cases(protocol)
    protocol_hash = checksum(protocol_path)
    frozen_path = directory / "frozen.json"
    binding = {"protocol_sha256": protocol_hash, "numerical_identity": identity}
    recorded_binding = directory / "binding.json"
    if recorded_binding.exists() and json.loads(recorded_binding.read_text()) != binding:
        raise ValueError("Evaluation protocol or numerical runtime changed; use a new protocol")
    atomic_json(recorded_binding, binding)
    if phase not in ("development", "test"):
        raise ValueError("Evaluation phase must be development or test")
    frozen = json.loads(frozen_path.read_text()) if frozen_path.exists() else None
    if frozen:
        if (
            frozen["binding"] != binding
            or checksum(directory / "candidate.json") != frozen["candidate_sha256"]
        ):
            raise ValueError("Frozen candidate integrity mismatch")
        if phase == "development":
            return json.loads((directory / "development-evaluation.json").read_text())
    elif phase == "test":
        raise ValueError("Test recordings require a frozen development candidate")
    if phase == "development" and (
        (directory / "test-access.json").exists()
        or any(
            json.loads(path.read_text()).get("partition") == "test"
            for path in (directory / "records").glob("*.json")
        )
    ):
        raise ValueError("Test access prevents re-fitting this protocol")
    if phase == "test" and not (directory / "test-access.json").exists():
        atomic_json(directory / "test-access.json", frozen)
    raw, records_dir = directory / "signals", directory / "records"
    raw.mkdir(exist_ok=True)
    records_dir.mkdir(exist_ok=True)
    selected = [row for row in registry if (row["partition"] != "test") == (phase == "development")]
    for index, row in enumerate(selected):
        filename = records_dir / (row["id"] + ".json")
        signal_path = raw / (row["id"] + ".parquet")
        if filename.exists():
            prior = json.loads(filename.read_text())
            if (
                prior["configuration_sha256"] != row["configuration_sha256"]
                or prior["binding"] != binding
                or not signal_path.is_file()
                or checksum(signal_path) != prior["signal_sha256"]
            ):
                raise ValueError("Corrupt evaluation checkpoint")
        else:
            cfg = SimulationConfig.model_validate(row["configuration"])
            dynamics = engine.simulate(cfg)
            clean = recorder.record(cfg, dynamics)
            signal = add_noise(clean, cfg.seed, cfg.noise_uv)
            values = features(dynamics.time_ms, signal)
            pending = signal_path.with_suffix(".parquet.pending")
            pq.write_table(
                pa.table(
                    {"time_ms": dynamics.time_ms, "signal_uv": signal, "clean_signal_uv": clean}
                ),
                pending,
            )
            os.replace(pending, signal_path)
            prior = {
                **row,
                "binding": binding,
                "features": values.tolist(),
                "signal_sha256": checksum(signal_path),
                "solver_seconds": dynamics.seconds,
                "units": {"time": "ms", "signal": "uV"},
            }
            atomic_json(filename, prior)
        progress(
            json.dumps(
                {"phase": phase, "done": index + 1, "total": len(selected), "case": row["id"]}
            ),
            flush=True,
        )
    all_records = [
        json.loads((records_dir / (row["id"] + ".json")).read_text())
        for row in registry
        if (records_dir / (row["id"] + ".json")).exists()
    ]
    if phase == "development":
        import importlib.metadata

        models, development = {}, {}
        for region in protocol["regions"]:
            models[region], development[region] = fit_candidate(
                [row for row in all_records if row["region"] == region],
                protocol["regularization_C"],
            )
        pooled, pooled_metrics = fit_candidate(all_records, protocol["regularization_C"])
        candidate = {
            "id": protocol["id"],
            "binding": binding,
            "protocol": protocol,
            "feature_version": VERSION,
            "models": models,
            "pooled_model": pooled,
            "training_versions": {"scikit-learn": importlib.metadata.version("scikit-learn")},
        }
        report = {
            "phase": phase,
            "regions": development,
            "pooled": pooled_metrics,
            "test_accessed": False,
            "binding": binding,
        }
        atomic_json(directory / "candidate.json", candidate)
        atomic_json(directory / "development-evaluation.json", report)
        atomic_json(
            frozen_path,
            {"candidate_sha256": checksum(directory / "candidate.json"), "binding": binding},
        )
        return report
    candidate = json.loads((directory / "candidate.json").read_text())
    test = [row for row in all_records if row["partition"] == "test"]
    expected = len(protocol["regions"]) * protocol["split_groups_per_region"]["test"] * 3
    if len(test) != expected:
        raise ValueError("Incomplete held-out test")
    predictions = [
        str(
            linear_predictions(np.asarray([row["features"]]), candidate["models"][row["region"]])[0]
        )
        for row in test
    ]
    classes = candidate["pooled_model"]["classes"]
    report = {
        **summary(test, predictions, classes),
        "scope": protocol["scope"],
        "regions": {},
        "binding": binding,
        "candidate_sha256": frozen["candidate_sha256"],
        "features": FEATURES,
        "grouping": protocol["grouping"],
        "sizes": {
            name: sum(row["partition"] == name for row in all_records)
            for name in ("train", "validation", "test")
        },
        "limitations": [
            "Synthetic engineering model only; no biological or clinical validation.",
            "Four test configurations per region and class; "
            "paired conditions are not independent participants.",
            "Region is known; this is not an unknown-location recognition result.",
            "No probability calibration or validation outside protocol ranges.",
        ],
    }
    for region in protocol["regions"]:
        indices = [i for i, row in enumerate(test) if row["region"] == region]
        report["regions"][region] = summary(
            [test[i] for i in indices], [predictions[i] for i in indices], classes
        )
    report["pooled_signal_only"] = summary(
        test,
        linear_predictions(
            np.asarray([row["features"] for row in test]), candidate["pooled_model"]
        ),
        classes,
    )
    rng = np.random.default_rng(protocol["bootstrap"]["seed"])
    groups = sorted({row["group"] for row in test})
    correctness = np.array(
        [
            [predictions[i] == row["label"] for i, row in enumerate(test) if row["group"] == group]
            for group in groups
        ]
    )
    bootstrap = [
        float(correctness[rng.integers(0, len(groups), len(groups))].mean())
        for _ in range(protocol["bootstrap"]["replicates"])
    ]
    report["group_bootstrap_95_interval"] = np.percentile(bootstrap, [2.5, 97.5]).tolist()
    # Negative control: training labels only are shuffled. The held-out split and
    # the actual signals remain fixed; no model selection uses these outcomes.
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import balanced_accuracy_score

    negative = []
    for _ in range(20):
        guesses = [None] * len(test)
        for region in protocol["regions"]:
            rows = [
                row
                for row in all_records
                if row["partition"] == "train" and row["region"] == region
            ]
            model = candidate["models"][region]
            x = (np.array([row["features"] for row in rows]) - model["mean"]) / model["scale"]
            shuffled = LogisticRegression(C=model["C"], random_state=7, max_iter=2000)
            shuffled.fit(x, rng.permutation([row["label"] for row in rows]))
            indices = [i for i, row in enumerate(test) if row["region"] == region]
            tx = (np.array([test[i]["features"] for i in indices]) - model["mean"]) / model["scale"]
            for i, guess in zip(indices, shuffled.predict(tx), strict=True):
                guesses[i] = str(guess)
        negative.append(float(balanced_accuracy_score([row["label"] for row in test], guesses)))
    report["shuffled_labels_balanced_accuracy"] = negative
    for row, prediction in zip(test, predictions, strict=True):
        row["prediction"] = prediction
    atomic_json(directory / "dataset-registry.json", all_records)
    atomic_json(directory / "evaluation.json", report)
    atomic_json(directory / "classifier.json", {**candidate, "evaluation": report})
    return report
