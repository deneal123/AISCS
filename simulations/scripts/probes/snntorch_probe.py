"""Run the author's functions with exact inputs and an explicit event export."""

import ast
import contextlib
import gc
import hashlib
import importlib.metadata
import json
import sys
import time
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import torch

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)
SOURCE = Path("/work/source/fly_brain.py")
SOURCE_SHA256 = "d5683af29740827b23b595b07963c3645ed91c0d9969c6ceb3eb0aef3b5a8f83"
FIXED_SHA256 = "9cc2aa290e3694463ed4e3e81aac734eb62cf51282c3c4b542c32cf471107a2e"
sys.path.insert(0, "/work/source")
torch.set_num_threads(4)
torch.set_num_interop_threads(1)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(value), flush=True)


def namespace():
    """Avoid the unguarded CLI tail; retain every original function and constant."""
    source = SOURCE.read_text()
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    assert source_hash in {SOURCE_SHA256, FIXED_SHA256}
    tree = ast.parse(source)
    prefix = []
    boundary = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "neurons_list"
            for target in node.targets
        ):
            boundary = node.lineno
            break
        prefix.append(node)
    assert boundary is not None
    ns = {"__name__": "aspa_reviewed_author_prefix"}
    # Authorized pinned upstream execution; only the unguarded CLI tail is omitted.
    exec(compile(ast.Module(body=prefix, type_ignores=[]), str(SOURCE), "exec"), ns)  # noqa: S102
    assert ns["device"].type == "cpu"
    assert not ns["save_model_weights_to_hard_drive"]
    assert not ns["load_model_weights_from_hard_drive"]
    return ns, {
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "tail_excluded_from_line": boundary,
        "function_bodies_modified": source_hash == FIXED_SHA256,
        "compatibility_fix": "explicit integer dtype for sensory indices"
        if source_hash == FIXED_SHA256
        else None,
    }


def run(ns, neurons, connections, params, seed, name, sensory):
    import sensory_neurons

    torch.manual_seed(seed)
    np.random.seed(seed)
    ns["taste_sugar_sensing_neurons"] = sensory
    started = time.perf_counter()
    with (
        (OUT / (name + ".log")).open("w") as stream,
        contextlib.redirect_stdout(stream),
    ):
        values = ns["run_spiking_neural_network"](neurons, connections, params)
    steps = int(params["timesteps_to_run"] / params["dt"])
    assert values.shape == (steps, len(neurons))
    assert np.isfinite(values).all() and np.isin(values, [0, 1]).all()
    times, indices = np.nonzero(values)
    ids = neurons.index.to_numpy(dtype=np.int64)
    events = {
        "step": times.astype(np.int32),
        "neuron_index": indices.astype(np.int32),
        "neuron_id": ids[indices],
        "time_ms": (times.astype(np.float64) + 1) * params["dt"],
        "population_counts": values.sum(axis=1).astype(np.int64),
        "neuron_counts": values.sum(axis=0).astype(np.int64),
    }
    np.savez_compressed(OUT / (name + ".npz"), **events)
    fingerprint = hashlib.sha256()
    for key in ("step", "neuron_index", "neuron_id"):
        fingerprint.update(events[key].tobytes())
    row = {
        "name": name,
        "seed": seed,
        "steps": steps,
        "dt_ms": params["dt"],
        "neurons": len(neurons),
        "events": len(times),
        "active_neurons": int(np.unique(indices).size),
        "event_fingerprint": fingerprint.hexdigest(),
        "seconds": time.perf_counter() - started,
        "array_dtype": str(values.dtype),
        "finite_binary": True,
        "state_reset": "author function initializes membrane and previous spikes; same global Leaky object reused",
        "input_group_namespace": "author taste variable rebound to the explicitly selected registered list",
        "available_lists": [
            key for key in vars(sensory_neurons) if key.endswith("_neurons")
        ],
    }
    del values
    gc.collect()
    print(json.dumps(row), flush=True)
    return row


def software():
    ns, source = namespace()
    ids = np.array(
        [ns["taste_sugar_sensing_neurons"][0], 11, 12, 13, 14, 15], dtype=np.int64
    )
    neurons = pd.DataFrame({"fixture": np.ones(6)}, index=ids)
    csv = OUT / "software-fixture.csv"
    neurons.to_csv(csv)
    ns["config"]["path_completeness"] = str(csv)
    connections = pd.DataFrame(
        {
            "Presynaptic_Index": [0, 0, 1, 2, 3, 4, 5],
            "Postsynaptic_Index": [1, 1, 2, 3, 4, 5, 0],
            "Excitatory x Connectivity": [20, 20, 40, 40, -40, 40, 40],
        }
    )
    weights = ns["build_weights_matrix"](connections, 6, 0.05).to_dense().numpy()
    expected = np.zeros((6, 6), dtype=np.float32)
    for pre, post, signed in connections.itertuples(index=False, name=None):
        expected[post, pre] += signed * 0.05
    np.testing.assert_allclose(weights, expected)
    params = dict(ns["params"], timesteps_to_run=100)
    rows = []
    for i, seed in enumerate((1, 2, 3, 1)):
        rows.append(
            run(ns, neurons, connections, params, seed, f"software-{i}", [ids[0]])
        )
    assert rows[0]["event_fingerprint"] == rows[3]["event_fingerprint"]
    silent = run(ns, neurons, connections, params, 1, "software-no-input", [])
    assert silent["events"] == 0 and all(row["events"] > 0 for row in rows)
    save(
        "software.json",
        {
            "status": "passed",
            "native_test_suite": False,
            "scope": "own six-node fixture calls original matrix builder and simulation function",
            "matrix_orientation_and_duplicate_sum": True,
            "repeat_equal": True,
            "rows": rows,
            "silent": silent,
            "source": source,
        },
    )


def full():
    import sensory_neurons

    ns, source = namespace()
    params = dict(ns["params"])
    neurons = pd.read_csv(ns["config"]["path_completeness"], index_col=0)
    connections = pd.read_parquet(ns["config"]["path_connectivity"])
    assert neurons.index.is_unique and np.issubdtype(neurons.index.dtype, np.integer)
    n = len(neurons)
    for key in ("Presynaptic_Index", "Postsynaptic_Index"):
        assert connections[key].between(0, n - 1).all()
    assert np.isfinite(connections["Excitatory x Connectivity"]).all()
    coverage = []
    for name in (
        "taste_sugar_sensing_neurons",
        "olfaction_smell_sensing_neurons",
        "visual_optic_lobe_sensing_mi1_neurons",
        "auditory_sound_sensing_ammc_neurons",
    ):
        ids = getattr(sensory_neurons, name)
        matched = [int(value) for value in ids if value in neurons.index]
        missing = [int(value) for value in ids if value not in neurons.index]
        assert len(set(ids)) == len(ids)
        coverage.append(
            {
                "name": name,
                "requested": len(ids),
                "matched": len(matched),
                "missing": missing,
                "matched_ids": matched,
            }
        )
    save(
        "input-identity.json",
        {
            "neurons": n,
            "connectivity_rows": len(connections),
            "columns": list(connections.columns),
            "coverage": coverage,
            "inputs": {
                path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                for path in (
                    ns["config"]["path_completeness"],
                    ns["config"]["path_connectivity"],
                )
            },
            "default_params": params,
            "source": source,
        },
    )
    original = list(sensory_neurons.taste_sugar_sensing_neurons)
    runs = []
    for i, seed in enumerate((1, 2, 3, 1)):
        runs.append(
            run(
                ns, neurons, connections, params, seed, f"run-{i}-seed-{seed}", original
            )
        )
    repeat = runs[0]["event_fingerprint"] == runs[3]["event_fingerprint"]
    assert repeat
    groups = []
    short = dict(params, timesteps_to_run=100)
    for i, item in enumerate(coverage[1:], start=1):
        ids = list(getattr(sensory_neurons, item["name"]))
        groups.append(run(ns, neurons, connections, short, 1, f"group-{i}", ids))
    silent = run(ns, neurons, connections, short, 1, "no-input", [])
    assert silent["events"] == 0
    data = np.load(OUT / "run-0-seed-1.npz")
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), layout="constrained")
    duration = float(params["timesteps_to_run"])
    time_edges = np.r_[np.arange(0, duration, 10), duration]
    neuron_edges = np.r_[np.arange(0, n, 128), n]
    histogram, _, _ = np.histogram2d(
        data["neuron_index"], data["time_ms"], bins=(neuron_edges, time_edges)
    )
    assert int(histogram.sum()) == runs[0]["events"]
    image = axes[0].imshow(
        histogram,
        origin="lower",
        interpolation="nearest",
        aspect="auto",
        cmap="magma",
        extent=[0, duration, 0, n],
    )
    fig.colorbar(image, ax=axes[0], label="Events / time-index bin")
    axes[0].set(
        xlabel="Model update end (ms)",
        ylabel="Neuron index (bins of up to 128)",
        title="All recorded events, seed 1; time bins 10 ms, not anatomical regions",
    )
    axes[1].plot(
        (np.arange(len(data["population_counts"])) + 1) * params["dt"],
        data["population_counts"],
    )
    axes[1].set(
        xlabel="Model update end (ms)",
        ylabel="Emitting neurons / update",
        title="Population activity; no absolute biological rate calibration",
    )
    fig.suptitle(
        "SIM-022 | Actual sparse snnTorch port; no body or nociceptive scenario"
    )
    for suffix in ("png", "svg"):
        fig.savefig(OUT / ("spike-recordings." + suffix), dpi=160)
    plt.close(fig)
    save(
        "visualization.json",
        {
            "all_events_accounted": int(histogram.sum()),
            "total_events": runs[0]["events"],
            "time_bin_ms": 10,
            "maximum_index_bin_width": 128,
            "histogram_shape": list(histogram.shape),
            "raster_decimated": False,
            "anatomical_projection": False,
        },
    )
    fig, ax = plt.subplots(figsize=(10, 4), layout="constrained")
    labels = [
        item["name"].removesuffix("_neurons").replace("_", " ") for item in coverage
    ]
    ax.barh(labels, [x["matched"] for x in coverage], label="Matched exact IDs")
    ax.barh(
        labels,
        [len(x["missing"]) for x in coverage],
        left=[x["matched"] for x in coverage],
        color="#b44a46",
        label="IDs absent from this input",
    )
    ax.set(
        xlabel="Number of specified neurons",
        title="Registered sensory lists versus the port's exact graph",
    )
    ax.legend()
    for suffix in ("png", "svg"):
        fig.savefig(OUT / ("sensory-id-coverage." + suffix), dpi=160)
    plt.close(fig)
    missing_any = any(row["missing"] for row in coverage)
    result = {
        "status": "partial" if missing_any else "passed",
        "repeat_equal": repeat,
        "data_scope": "exact pinned FlyWire inputs; author sparse CPU default; four static sensory-group lists",
        "time_convention": "spike belongs to discrete update; time_ms is end of update, not substep threshold time",
        "runs": runs,
        "groups": groups,
        "no_input": silent,
        "coverage": coverage,
        "missing_registered_ids": missing_any,
        "native_test_suite": False,
        "biological_validation": False,
        "nociception": False,
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("torch", "snntorch", "numpy", "pandas", "fastparquet")
        },
    }
    save("functional.json", result)
    assert not missing_any, (
        "Some registered sensory IDs do not resolve; partial results retained"
    )


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "software":
        software()
    elif mode == "full":
        full()
    elif mode == "smoke":
        ns, _ = namespace()
        print("Author functions loaded; CPU; defaults:", ns["params"])
    else:
        raise ValueError(mode)
