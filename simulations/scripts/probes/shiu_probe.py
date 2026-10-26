"""Exercise unchanged original Shiu functions, separating fixture and real graph."""

import ast
import gc
import hashlib
import json
import sys
import time
from pathlib import Path

import brian2 as b2
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, "/work/source")
import model
import utils

OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)
b2.prefs.codegen.target = "cython"
b2.prefs.codegen.runtime.cython.cache_dir = "/work/env/brian-cache"
b2.defaultclock.dt = 0.1 * b2.ms


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n")
    print(name, json.dumps(value), flush=True)


def parameters(duration_ms=100, rate=150, rate2=0):
    p = dict(model.default_params)
    p.update(
        t_run=duration_ms * b2.ms, n_run=1, r_poi=rate * b2.Hz, r_poi2=rate2 * b2.Hz
    )
    return p


def setup(seed, paths, p, exc, exc2=(), silence=()):
    b2.start_scope()
    b2.seed(seed)
    neu, syn, monitor = model.create_model(*paths, p)
    inputs, neu = model.poi(neu, list(exc), list(exc2), p)
    syn = model.silence(list(silence), syn)
    network = b2.Network(neu, syn, monitor, *inputs)
    return neu, syn, monitor, network


def fixture():
    directory = OUT / "fixture"
    directory.mkdir(exist_ok=True)
    ids = np.arange(720575940624963780, 720575940624963786, dtype=np.int64)
    comp = directory / "completeness.csv"
    conn = directory / "connectivity.parquet"
    pd.DataFrame(index=ids).to_csv(comp)
    pre = np.array([0, 1, 2, 3, 4], dtype=np.int64)
    post = np.array([1, 2, 3, 4, 5], dtype=np.int64)
    # A single 100-contact impulse peaks below the 7-mV threshold gap.
    # This artificial chain uses 400 contacts so propagation is an explicit
    # suprathreshold software condition, not a biological weight calibration.
    weights = np.full(5, 400, dtype=np.int64)
    pd.DataFrame(
        {
            "Presynaptic_Index": pre,
            "Postsynaptic_Index": post,
            "Excitatory x Connectivity": weights,
        }
    ).to_parquet(conn)
    traces = []
    for seed, name, off in [
        (1, "intact", []),
        (1, "repeat", []),
        (1, "output-zero", [1]),
    ]:
        neu, syn, mon, net = setup(seed, (comp, conn), parameters(), [0], silence=off)
        if off:
            assert syn.w[0] != 0 * b2.mV  # Incoming 0->1 is retained.
            assert syn.w[1] == 0 * b2.mV  # Only outgoing 1->2 is disabled.
        net.run(100 * b2.ms)
        save(
            "software-" + name + ".json",
            {"counts": mon.count[:].tolist(), "scope": "artificial 400-contact chain"},
        )
        events = np.c_[mon.i[:], np.rint(mon.t[:] / b2.ms / 0.1).astype(np.int64)]
        traces.append(events)
        if off:
            assert np.any(mon.i[:] == 1) and not np.any(mon.i[:] >= 2)
        else:
            assert np.any(mon.i[:] == 5)
        del net, neu, syn, mon
        gc.collect()
    np.testing.assert_array_equal(traces[0], traces[1])
    neu, syn, mon, net = setup(1, (comp, conn), parameters(), [])
    net.run(100 * b2.ms)
    assert len(mon.i[:]) == 0
    assert len(syn) == 5 and np.allclose(neu.v[:] / b2.mV, -52)
    save(
        "software.json",
        {
            "passed": True,
            "scope": "own six-neuron software fixture; original functions, not biological validation",
            "cython_backend": True,
            "same_seed_exact": True,
            "outgoing_only_silence_confirmed": True,
            "incoming_connection_retained": True,
            "no_input_events": 0,
            "exact_int64_ids": ids.tolist(),
        },
    )


def real_paths():
    root = Path("/work/source")
    return (
        root / "2023_03_23_completeness_630_final.csv",
        root / "2023_03_23_connectivity_630_final.parquet",
    )


def source_ids():
    notebook = json.loads(Path("/work/source/example.ipynb").read_text())
    for cell in notebook["cells"]:
        code = "".join(cell.get("source", []))
        if code.lstrip().startswith("neu_sugar ="):
            return ast.literal_eval(ast.parse(code).body[0].value)
    raise ValueError("Original sensory list not found")


def check_data():
    comp, conn = real_paths()
    catalog = pd.read_csv(comp, index_col=0)
    graph = pd.read_parquet(conn)
    ids = catalog.index.to_numpy()
    assert ids.dtype == np.int64 and len(np.unique(ids)) == len(ids) == 127400
    pre = graph["Presynaptic_Index"].to_numpy()
    post = graph["Postsynaptic_Index"].to_numpy()
    assert pre.dtype.kind in "iu" and post.dtype.kind in "iu"
    assert len(graph) == 14687178
    for index in [pre, post]:
        assert index.min() >= 0 and index.max() < len(ids)
    for col, index in [("Presynaptic_ID", pre), ("Postsynaptic_ID", post)]:
        np.testing.assert_array_equal(graph[col].to_numpy(), ids[index])
    assert np.isfinite(graph["Excitatory x Connectivity"]).all()
    found = catalog.index.get_indexer(source_ids())
    assert np.all(found >= 0) and len(found) == 21
    save(
        "data-identity.json",
        {
            "passed": True,
            "neurons": len(ids),
            "edge_rows": len(graph),
            "columns": graph.columns.tolist(),
            "sugar_ids": source_ids(),
            "sugar_indices": found.tolist(),
            "all_endpoint_ids_checked": True,
            "scope": "original pinned v630 bytes and every stored endpoint; no substitution with v783",
        },
    )


def run_one(seed, name, exc, silence=(), rate=150, exc2=(), rate2=0, duration_ms=100):
    comp, conn = real_paths()
    ids = pd.read_csv(comp, index_col=0).index.to_numpy()
    p = parameters(duration_ms, rate, rate2)
    started = time.perf_counter()
    neu, syn, mon, net = setup(seed, (comp, conn), p, exc, exc2, silence)
    assert len(neu) == 127400 and len(syn) == 14687178
    net.run(p["t_run"])
    for state in [neu.v[:] / b2.mV, neu.g[:] / b2.mV]:
        assert np.isfinite(state).all()
    index = np.asarray(mon.i[:], dtype=np.int32)
    times = np.asarray(mon.t[:] / b2.ms, dtype=np.float64)
    step = np.rint(times / 0.1).astype(np.int32)
    assert np.allclose(times, step.astype(float) * 0.1, atol=1e-9, rtol=0)
    assert np.all(times >= 0) and np.all(times < duration_ms)
    order = np.lexsort((index, step))
    events = np.c_[step[order].astype(np.int64), ids[index[order]]]
    trains = model.get_spk_trn(mon)
    table = model.construct_dataframe([trains], name, dict(enumerate(ids)))
    assert len(table) == len(index)
    assert len(table) == 0 or table.flywire_id.dtype == np.int64
    table.to_parquet(OUT / (name + ".parquet"), compression="brotli")
    table.to_csv(OUT / (name + ".csv"), index=False)
    np.savez_compressed(
        OUT / (name + ".npz"),
        neuron_index=index,
        neuron_id=ids[index],
        time_ms=times,
        step=step,
        ids=ids,
        final_v_mv=np.asarray(neu.v[:] / b2.mV),
        final_g_mv=np.asarray(neu.g[:] / b2.mV),
    )
    if len(table):
        rates, _ = utils.get_rate(table, duration_ms / 1000, 1)
        assert int(np.rint((rates[name] * duration_ms / 1000).sum())) == len(index)
    info = {
        "name": name,
        "seed": seed,
        "duration_ms": duration_ms,
        "events": len(index),
        "active_neurons": len(np.unique(index)),
        "event_fingerprint": hashlib.sha256(events.tobytes()).hexdigest(),
        "wall_seconds": time.perf_counter() - started,
        "exc_indices": list(exc),
        "exc2_indices": list(exc2),
        "output_silenced_indices": list(silence),
        "rate_hz": rate,
        "rate2_hz": rate2,
        "event_time_unit": "ms",
        "author_parquet_t_unit": "seconds",
        "dt_ms": 0.1,
    }
    save(name + ".json", info)
    del net, neu, syn, mon
    gc.collect()
    return info


def full():
    data = json.loads((OUT / "data-identity.json").read_text())
    exc = data["sugar_indices"]
    runs = [
        run_one(seed, name, exc)
        for seed, name in [
            (1, "seed-1"),
            (2, "seed-2"),
            (3, "seed-3"),
            (1, "seed-1-repeat"),
        ]
    ]
    assert runs[0]["event_fingerprint"] == runs[3]["event_fingerprint"]
    variants = [
        run_one(1, "no-input", [], duration_ms=50),
        run_one(1, "output-zero", exc, silence=exc, duration_ms=50),
        run_one(
            1,
            "two-input-rates",
            exc[:10],
            rate=100,
            exc2=exc[10:],
            rate2=50,
            duration_ms=50,
        ),
    ]
    assert variants[0]["events"] == 0
    # Disabling outputs does not silence the directly forced cells themselves.
    a = np.load(OUT / "output-zero.npz")
    assert set(a["neuron_index"].tolist()).issubset(set(exc))
    api = public_api(runs[0]["event_fingerprint"])
    plot()
    save(
        "functional.json",
        {
            "status": "passed",
            "runs": runs,
            "variants": variants,
            "repeat_equal": True,
            "backend": "original Brian2 model, Cython runtime",
            "public_api": api,
            "original_default_params_unchanged": True,
            "overrides": "duration 100/50 ms, one trial, explicit seeds, dt=0.1 ms and configured input/control groups; no parameter fitting or source-body edits",
            "limits": [
                "Brain v630 has no body/environment or calibrated nociceptive stimulus",
                "silence() zeroes outgoing weights; incoming weights and direct Poisson-driven spikes remain",
                "Input Poisson targets have refractory duration set to zero by original code",
                "No physical CAP/ECAP recording operator",
                "Linux/Python environment follows main numpy=1.24 specification; Windows full lock differs and is not reproduced bit-for-bit",
            ],
        },
    )


def public_api(expected_fingerprint):
    """Exercise the actual FlyWire-ID entry point and original Parquet writer."""
    b2.start_scope()
    b2.seed(1)
    comp, conn = real_paths()
    model.run_exp(
        "author-api",
        source_ids(),
        OUT,
        comp,
        conn,
        params=parameters(),
        n_proc=1,
        force_overwrite=True,
    )
    path = OUT / "author-api.parquet"
    table = utils.load_exps([path])
    assert table.flywire_id.dtype == np.int64
    step = np.rint(table.t.to_numpy() * 1000 / 0.1).astype(np.int64)
    ids = table.flywire_id.to_numpy()
    order = np.lexsort((ids, step))
    fingerprint = hashlib.sha256(np.c_[step[order], ids[order]].tobytes()).hexdigest()
    assert fingerprint == expected_fingerprint
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    model.run_exp(
        "author-api",
        [],
        OUT,
        "/work/not-read.csv",
        "/work/not-read.parquet",
        params=parameters(),
        n_proc=1,
        force_overwrite=False,
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    info = {
        "passed": True,
        "entrypoint": "unmodified model.run_exp",
        "n_proc": 1,
        "n_run": 1,
        "events": len(table),
        "all_event_times_and_ids_match_direct_functions": True,
        "event_fingerprint": fingerprint,
        "existing_output_skip_verified": True,
        "time_unit": "seconds in original Parquet; converted explicitly to 0.1-ms steps",
    }
    save("public-api.json", info)
    return info


def plot():
    with np.load(OUT / "seed-1.npz") as a:
        times, ids = a["time_ms"], a["neuron_index"]
    fig, axs = plt.subplots(2, 1, figsize=(11, 7), constrained_layout=True)
    axs[0].scatter(times, ids, s=2)
    axs[0].set(
        xlabel="Model time (ms)",
        ylabel="Neuron index (v630)",
        title="Original Shiu model: recorded spike events, seed 1",
    )
    for name in ["seed-1", "seed-2", "seed-3", "seed-1-repeat"]:
        with np.load(OUT / (name + ".npz")) as a:
            hist, edges = np.histogram(a["time_ms"], bins=np.arange(0, 101, 5))
            assert int(hist.sum()) == len(a["time_ms"])
        axs[1].stairs(
            hist,
            edges,
            label=name,
            linestyle="--" if name.endswith("repeat") else "-",
        )
    axs[1].set(
        xlabel="Model time (ms)",
        ylabel="Events / 5 ms",
        title="Seeded 21-neuron sugar-input scenario; no nociception claim",
    )
    axs[1].legend()
    for suffix in ["png", "svg"]:
        fig.savefig(OUT / ("original-lif-events." + suffix), dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    {"software": fixture, "data": check_data, "full": full}[sys.argv[1]]()
