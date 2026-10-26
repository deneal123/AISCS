"""Check the author's structural controls and bounded full-network execution."""

import gc
import hashlib
import importlib.metadata
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

sys.path.insert(0, "/work/source/scripts")
import build_degree_preserving_random_mask as builder
import revision_control_utils as rc
from degree_preserving_mask_utils import init_degree_preserving_random_network
from random_mask_utils import load_base_connectome, save_random_mask

OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(obj), flush=True)


def fingerprint(source, target):
    h = hashlib.sha256(source.astype("<i8").tobytes())
    h.update(target.astype("<i8").tobytes())
    return h.hexdigest()


def software():
    source = np.array([0, 1, 2, 3, 4, 5, 0, 2])
    target = np.array([1, 2, 3, 4, 5, 0, 0, 2])
    runs = []
    for seed in (1, 2, 3, 1):
        a, b, stats = builder.swap_degree_preserving_edges(
            source,
            target,
            n_nodes=6,
            rng=np.random.default_rng(seed),
            n_swaps=20,
            max_attempt_factor=20,
        )
        assert np.array_equal(
            np.bincount(a, minlength=6), np.bincount(source, minlength=6)
        )
        assert np.array_equal(
            np.bincount(b, minlength=6), np.bincount(target, minlength=6)
        )
        assert set(zip(a[a == b], b[a == b])) == {(0, 0), (2, 2)}
        assert len(set(zip(a, b))) == len(source) and stats["accepted_swaps"] == 20
        runs.append(dict(stats, seed=seed, sha256=fingerprint(a, b)))
    assert runs[0]["sha256"] == runs[3]["sha256"]
    save(
        "software.json",
        {
            "scope": "own six-node fixture calls original swap function",
            "native_test_suite": False,
            "repeat_equal": True,
            "runs": runs,
            "versions": {
                x: importlib.metadata.version(x)
                for x in ("torch", "flyvis", "numpy", "datamate")
            },
        },
    )


def full():
    started = time.monotonic()
    from datamate import Directory

    storage = []
    for location in ("/work/cache/hdf-diagnostic", "/tmp/aspa-hdf-diagnostic"):
        try:
            directory = Directory(Path(location))
            labels = np.array([b"R1", b"R2", b"T4a"])
            directory["labels"] = labels
            restored = directory["labels"][:]
            assert np.array_equal(labels, restored)
            storage.append({"path": location, "status": "passed"})
        except (OSError, RuntimeError, ValueError, AssertionError) as exc:
            storage.append({"path": location, "status": "failed", "error": repr(exc)})
    save(
        "storage-diagnostic.json",
        {
            "checks": storage,
            "model_cache": "/tmp/aspa-flyvis inside the owned disposable container",
        },
    )
    base = load_base_connectome()
    source = np.asarray(base.edges.source_index[:], dtype=np.int64)
    target = np.asarray(base.edges.target_index[:], dtype=np.int64)
    nodes = np.asarray(base.nodes.type[:])
    n_nodes = len(nodes)
    import flyvis

    spec = Path(flyvis.connectome_file)
    assert source.min() >= 0 and target.min() >= 0
    assert source.max() < n_nodes and target.max() < n_nodes < 2**32
    np.savez_compressed(
        OUT / "base-edges.npz", source=source.astype("<u4"), target=target.astype("<u4")
    )
    save(
        "base-graph.json",
        {
            "nodes": n_nodes,
            "edges": len(source),
            "source": "installed FlyVis 1.2.0 connectome/model configuration",
            "scope": "visual average-filter model, not a whole-brain FlyWire v630 graph",
            "fingerprint": fingerprint(source, target),
            "cell_types": len(np.unique(nodes)),
            "default_spec_file": spec.name,
            "default_spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
        },
    )
    runs = []
    for number, seed in enumerate((1, 2, 3, 1)):
        begin = time.monotonic()
        payload = builder.build_payload(seed, n_swaps=250000, max_attempt_factor=20)
        edges = payload["edges"]
        a, b = edges["source_index"], edges["target_index"]
        assert np.array_equal(
            np.bincount(source, minlength=n_nodes), np.bincount(a, minlength=n_nodes)
        )
        assert np.array_equal(
            np.bincount(target, minlength=n_nodes), np.bincount(b, minlength=n_nodes)
        )
        # Audit the unchanged edge metadata against the actual rewired endpoints.
        mismatch = {
            key: int(
                np.count_nonzero(
                    np.asarray(edges[key]).astype(str) != nodes[indices].astype(str)
                )
            )
            for key, indices in (("source_type", a), ("target_type", b))
        }
        entry = {
            "seed": seed,
            "sha256": fingerprint(a, b),
            "stats": payload["stats"],
            "endpoint_type_metadata_mismatches": mismatch,
            "seconds": time.monotonic() - begin,
        }
        runs.append(entry)
        print("mask", json.dumps(entry), flush=True)
        if number == 0:
            save_random_mask(payload, Path("/work/cache/degree-preserving.pt"))
        if number < 3:
            np.savez_compressed(OUT / f"target-seed-{seed}.npz", target=b.astype("<u4"))
        del payload
        gc.collect()
    assert runs[0]["sha256"] == runs[3]["sha256"]
    save(
        "structural-controls.json",
        {
            "runs": runs,
            "repeat_equal": True,
            "scope": "author default 250000 accepted swaps; no inferential ensemble claim",
        },
    )
    # Short numerical health check on the full configured network. This is not
    # a reproduction of the author's full MovingEdge training benchmark.
    trials = []
    for number, seed in enumerate((1, 2, 3, 1)):
        for kind in ("connectome", "degreepres"):
            rc.set_global_seed(seed)
            factory = (
                rc.init_connectome_network_from_scratch
                if kind == "connectome"
                else (
                    lambda s: init_degree_preserving_random_network(
                        "/work/cache/degree-preserving.pt", s
                    )
                )
            )
            network = factory(seed)
            inputs = network.stimulus.n_input_elements
            stimuli = torch.full((1, 4, 1, inputs), 0.5)
            stimuli[:, 1:3, :, : inputs // 2] = 1
            initial = network.steady_state(0.04, 0.02, batch_size=1, value=0.5)
            activity = (
                network.simulate(stimuli, dt=0.02, initial_state=initial)
                .detach()
                .cpu()
                .numpy()
            )
            repeated = (
                network.simulate(stimuli, dt=0.02, initial_state=initial)
                .detach()
                .cpu()
                .numpy()
            )
            assert activity.shape == (1, 4, n_nodes) and np.isfinite(activity).all()
            assert np.array_equal(activity, repeated)
            digest = hashlib.sha256(activity.astype("<f4").tobytes()).hexdigest()
            np.save(OUT / f"activity-{kind}-{number}.npy", activity, allow_pickle=False)
            trials.append(
                {
                    "seed": seed,
                    "kind": kind,
                    "sha256": digest,
                    "shape": list(activity.shape),
                    "reset_exact": True,
                    "mean_abs": float(np.abs(activity).mean()),
                    "mean_by_frame": activity.mean(axis=(0, 2)).tolist(),
                }
            )
            del network, activity, repeated
            gc.collect()
    for kind in ("connectome", "degreepres"):
        same = [x for x in trials if x["kind"] == kind and x["seed"] == 1]
        assert same[0]["sha256"] == same[1]["sha256"]
    pd.DataFrame(trials).to_csv(OUT / "numerical-trials.csv", index=False)
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout="constrained")
    for entry in trials[:6]:
        axes[0].plot(
            np.arange(1, 5) * 0.02,
            entry["mean_by_frame"],
            "o-" if entry["kind"] == "connectome" else "s--",
            color="#205d89" if entry["kind"] == "connectome" else "#c46635",
            alpha=0.65,
            label=f"{entry['kind']}, seed {entry['seed']}",
        )
    axes[0].set(
        xlabel="Time after initial state (s)",
        ylabel="Mean model activity (model units)",
        title="Short untrained numerical check",
    )
    axes[0].legend(fontsize=8)
    mismatch = [r["endpoint_type_metadata_mismatches"]["target_type"] for r in runs]
    axes[1].bar(
        ["seed 1", "seed 2", "seed 3", "seed 1 repeat"], mismatch, color="#c46635"
    )
    axes[1].set(
        ylabel="Edges with target-type / endpoint mismatch",
        title="Audit of the author's rewired metadata",
    )
    fig.suptitle(
        "SIM-018 | Software checks; not a reproduction of published training results",
        fontsize=12,
    )
    for suffix in ("png", "svg"):
        fig.savefig(OUT / ("control-study-checks." + suffix), dpi=160)
    plt.close(fig)
    training = []
    for number, seed in enumerate((1, 2, 3, 1)):
        for kind in ("connectome", "degreepres"):
            factory = (
                rc.init_connectome_network_from_scratch
                if kind == "connectome"
                else (
                    lambda s: init_degree_preserving_random_network(
                        "/work/cache/degree-preserving.pt", s
                    )
                )
            )
            curve, summary = rc.run_fixed_steps(
                model_kind=kind,
                seed=seed,
                max_iters=2,
                learning_rate=1e-3,
                stimuli=stimuli,
                targets=torch.tensor([[0.0, 1.0]]),
                feature_start=0,
                feature_stop=4,
                dt=0.02,
                steady_state_seconds=0.04,
                network_factory=factory,
            )
            numeric = curve[
                ["task_loss", "activity_abs_mean", "gradient_norm"]
            ].to_numpy(dtype="<f8")
            assert summary["remained_finite"] and summary["iterations_completed"] == 2
            assert np.isfinite(numeric).all() and (numeric[:, 2] > 0).all()
            curve.to_csv(OUT / f"training-{kind}-{number}.csv", index=False)
            training.append(
                {
                    "seed": seed,
                    "kind": kind,
                    "numeric_sha256": hashlib.sha256(numeric.tobytes()).hexdigest(),
                    "summary": summary,
                }
            )
    for kind in ("connectome", "degreepres"):
        repeats = [x for x in training if x["kind"] == kind and x["seed"] == 1]
        assert repeats[0]["numeric_sha256"] == repeats[1]["numeric_sha256"]
    save(
        "training-check.json",
        {
            "trials": training,
            "repeat_equal": True,
            "scope": "author optimizer/decoder path, two steps on one synthetic diagnostic input",
            "target": "arbitrary diagnostic vector [0, 1], not an observed motion label",
            "not_claimed": "MovingEdge benchmark reproduction or biological/predictive performance",
        },
    )
    save(
        "functional.json",
        {
            "scope": "full configured graph, bounded synthetic visual input; untrained models",
            "nodes": n_nodes,
            "edges": len(source),
            "masks": runs,
            "trials": trials,
            "repeat_equal": True,
            "dt_seconds": 0.02,
            "frames": 4,
            "input": "constant intensity with a two-frame half-field increment, not published MovingEdge benchmark",
            "activity_units": "model state, not mV or ECAP",
            "seconds": time.monotonic() - started,
            "not_verified": [
                "published training curves and conclusions",
                "pretrained checkpoint",
                "human transfer",
                "nociception or pain",
            ],
        },
    )


if __name__ == "__main__":
    {"software": software, "full": full}[sys.argv[1]]()
