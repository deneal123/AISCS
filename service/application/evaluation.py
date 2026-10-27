from pathlib import Path

import numpy as np

from service.contracts import SimulationConfig
from service.domain.ports import NumericalEngine, RecordingOperator
from service.domain.signals import FEATURES, features
from service.shared.json_io import write_json


def evaluate_classifier(
    directory: Path, engine: NumericalEngine, recorder: RecordingOperator
) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import balanced_accuracy_score, confusion_matrix
    from sklearn.preprocessing import StandardScaler

    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261027)
    assignments = np.array(["train"] * 18 + ["validation"] * 6 + ["test"] * 6)
    rng.shuffle(assignments)
    records, x, labels = [], [], []
    # Each seed/configuration contributes all three classes to the SAME partition.
    for group, partition in enumerate(assignments):
        excitability, adaptation = rng.uniform(0.9, 1.1), rng.uniform(0.1, 0.5)
        for label in ["none", "weak", "strong"]:
            cfg = SimulationConfig(
                seed=1000 + group,
                stimulus=label,
                excitability=float(excitability),
                adaptation=float(adaptation),
            )
            dynamics = engine.simulate(cfg)
            clean = recorder.record(cfg, dynamics)
            noise = np.random.default_rng(np.random.SeedSequence([cfg.seed, 917]))
            signal = clean + noise.normal(0, cfg.noise_uv, clean.shape)
            values = features(dynamics.time_ms, signal)
            x.append(values)
            labels.append(label)
            records.append(
                {
                    "group": group,
                    "seed": cfg.seed,
                    "partition": partition,
                    "label": label,
                    "configuration_sha256": cfg.digest(),
                    "features": values.tolist(),
                    "solver_seconds": dynamics.seconds,
                }
            )
    x, labels = np.asarray(x), np.asarray(labels)
    partitions = np.array([row["partition"] for row in records])
    train, validation, test = (partitions == name for name in ["train", "validation", "test"])
    scaler = StandardScaler().fit(x[train])
    best, best_score = None, -1.0
    for regularization in [0.1, 1.0, 10.0]:
        candidate = LogisticRegression(C=regularization, random_state=7, max_iter=1000)
        candidate.fit(scaler.transform(x[train]), labels[train])
        score = balanced_accuracy_score(
            labels[validation], candidate.predict(scaler.transform(x[validation]))
        )
        if score > best_score:
            best, best_score = candidate, float(score)
    predicted = best.predict(scaler.transform(x[test]))
    for record, guess in zip(np.array(records, dtype=object)[test], predicted, strict=True):
        record["prediction"] = str(guess)
    shuffled = LogisticRegression(C=best.C, random_state=7, max_iter=1000)
    shuffled.fit(scaler.transform(x[train]), rng.permutation(labels[train]))
    report = {
        "scope": "Synthetic author-defined model only; no biological/clinical validation",
        "features": FEATURES,
        "grouping": "same seed and configuration kept together",
        "sizes": {
            name: int(np.sum(partitions == name)) for name in ["train", "validation", "test"]
        },
        "groups": {
            name: int(np.sum(assignments == name)) for name in ["train", "validation", "test"]
        },
        "validation_balanced_accuracy": best_score,
        "test_balanced_accuracy": float(balanced_accuracy_score(labels[test], predicted)),
        "majority_baseline_balanced_accuracy": 1 / 3,
        "shuffled_labels_balanced_accuracy": float(
            balanced_accuracy_score(labels[test], shuffled.predict(scaler.transform(x[test])))
        ),
        "classes": best.classes_.tolist(),
        "confusion_matrix": confusion_matrix(
            labels[test], predicted, labels=best.classes_
        ).tolist(),
        "test_realizations": int(test.sum()),
        "selected_C_on_validation": best.C,
        "limitations": [
            "Small test set: 6 independent configurations per class.",
            "No probability calibration or human data.",
            "Electrode displacement/noise-domain generalization requires separate validation.",
        ],
    }
    write_json(directory / "evaluation.json", report)
    write_json(directory / "dataset-registry.json", records)
    write_json(
        directory / "classifier.json",
        {
            "feature_names": FEATURES,
            "classes": best.classes_.tolist(),
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
            "coefficients": best.coef_.tolist(),
            "intercepts": best.intercept_.tolist(),
            "evaluation": report,
        },
    )
    return report
