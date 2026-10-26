"""Execute upstream LIF functions; explicitly separate fixture and v783 trials."""

import csv
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/work/source")
import brian2 as b
import numpy as np
from vis_fly import lif_simulation as model
from vis_fly.process_csv import (
    import_csv_connectome,
    modify_synapses_sign,
    predict_neuron_transmitters,
)
from vis_fly.structures import Connectome

b.prefs.codegen.target = "numpy"  # Supported headless CPU backend, same equations.
OUT = Path(os.environ.get("ASPA_FLYLIF_EXPORT_DIR", "/work/export")).resolve()
if not OUT.is_relative_to(Path("/work")):
    raise ValueError("Export must stay within this run")
OUT.mkdir(exist_ok=True)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def reset(seed):
    b.start_scope()
    b.seed(seed)
    np.random.seed(seed)
    b.defaultclock.dt = 0.1 * b.ms


def fixture():
    c = Connectome()
    for edge in [
        ["a", "b", "fixture", "8", "ACH"],
        ["b", "c", "fixture", "8", "ACH"],
        ["c", "d", "fixture", "8", "ACH"],
        ["d", "a", "fixture", "1", "GABA"],
    ]:
        c.add_synapse(edge)
    return c


def smoke():
    import brian2tools
    import markdown_strings

    assert markdown_strings.header("Probe", 1) == "# Probe"
    repeats = []
    for seed in [1, 2, 3, 1]:
        reset(seed)
        result = model.simulation_single(
            fixture(), [[0]], 2000 * b.Hz, 100 * b.ms, [[0, 1, 2, 3]], 1
        )
        repeats.append(result)
    for key in repeats[0]:
        assert all(
            np.array_equal(a, z) for a, z in zip(repeats[0][key], repeats[3][key])
        )
    times, voltage = result["state_t"][0], result["state_v"][0]
    assert voltage.shape == (4, 1000) and len(times) == 1000
    assert np.isfinite(voltage).all() and np.isfinite(times).all()
    assert np.allclose(np.diff(times), 0.1, atol=1e-5)
    assert len(result["spike_i"][0]) > 0
    reset(1)
    quiet = model.simulation_single(
        fixture(), [[0]], 0 * b.Hz, 100 * b.ms, [[0, 1, 2, 3]], 1
    )
    assert len(quiet["spike_i"][0]) == 0
    reset(1)
    suppressed = model.simulation_single(
        fixture(),
        [[0]],
        2000 * b.Hz,
        100 * b.ms,
        [[0, 1, 2, 3]],
        1,
        silence_neurons=[1],
    )
    assert not np.isin(suppressed["spike_i"][0], [1, 2, 3]).any()
    save(
        "smoke.json",
        {
            "status": "passed",
            "scope": "four-neuron software fixture, not connectome",
            "voltage_shape": list(voltage.shape),
            "dt_ms": 0.1,
            "spikes": len(result["spike_i"][0]),
            "backend": "numpy",
            "brian2": b.__version__,
            "numpy": np.__version__,
            "brian2tools": brian2tools.__version__,
            "repeat_seed_equal": True,
            "zero_drive_quiescent": True,
            "silenced_chain_downstream_quiescent": True,
        },
    )
    with (OUT / "fixture-voltage.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["time_ms", "unit0_mV", "unit1_mV", "unit2_mV", "unit3_mV"])
        writer.writerows(zip(times.tolist(), *voltage.tolist()))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), layout="constrained")
    for i in range(4):
        axes[0].plot(times, voltage[i], label=f"unit {i}")
    axes[0].set(xlabel="Model time (ms)", ylabel="Simulated voltage (mV)")
    axes[0].legend(ncol=4)
    axes[1].scatter(result["spike_t"][0], result["spike_i"][0], marker="|", s=35)
    axes[1].set(xlabel="Model time (ms)", ylabel="Unit index", yticks=range(4))
    fig.suptitle(
        "Four-neuron software fixture: upstream LIF equations\nPoisson drive and a signed chain; no connectome or biological validation"
    )
    for ext in ("png", "svg"):
        fig.savefig(OUT / ("lif-fixture." + ext), dpi=180)
    plt.close(fig)


def functional():
    manifest = json.loads(Path("/work/flylif-inputs.json").read_text())
    for item in manifest["inputs"]:
        path = Path("/work") / item["derived_file"]
        with path.open("rb") as stream:
            assert (
                hashlib.file_digest(stream, "sha256").hexdigest()
                == item["derived_sha256"]
            )
    c = import_csv_connectome(
        "/work/cache/flywire/connections_no_threshold.csv",
        "/work/cache/flywire/visual_neuron_types.csv",
        "/work/cache/flywire/column_assignment.csv",
    )
    predict_neuron_transmitters(c)
    modify_synapses_sign(c)
    stimulus = [
        n.name
        for n in c.neurons
        if n.visual_type and n.visual_type.type in {"L1", "L2", "L3"}
    ][:6]
    # Select from input connectivity before simulation, rather than choosing
    # units after observing an attractive response. This is a functional probe,
    # not the author's orientation-map sampling protocol.
    stimulated_indices = {c.get_neuron_idx2(n) for n in stimulus}
    strengths = {}
    for edge in c.synapses:
        target = c.neurons[edge.to_neuron]
        if (
            edge.from_neuron in stimulated_indices
            and edge.weight_signed > 0
            and target.name not in stimulus
            and target.visual_type
        ):
            strengths[target.name] = (
                strengths.get(target.name, 0.0) + edge.weight_signed
            )
    observed = sorted(strengths, key=lambda n: (-strengths[n], n))[:12]
    assert len(stimulus) == 6 and len(observed) == 12
    cases = []
    for seed in [1, 2, 3, 1]:
        reset(seed)
        rates = model.run_stimulus_monitor(
            c,
            stimulus,
            [10] * len(stimulus),
            observed,
            sim_time=100 * b.ms,
            sim_freq=200 * b.Hz,
        )
        rates = {k: float(v) for k, v in rates.items()}
        assert set(rates) == set(observed) and all(
            np.isfinite(v) and v >= 0 for v in rates.values()
        )
        cases.append({"seed": seed, "rates_hz": rates})
        print("Alternate v783 run", seed, "completed", flush=True)
    assert cases[0] == cases[3]
    reset(1)
    quiet = model.run_stimulus_monitor(
        c,
        stimulus,
        [10] * len(stimulus),
        observed,
        sim_time=100 * b.ms,
        sim_freq=0 * b.Hz,
    )
    assert all(v == 0 for v in quiet.values())
    for n in c.neurons:
        n.SIM_flag = 16 if n.name in observed else 1 if n.name in stimulus else 0
    model.sort_connectome(c)
    stim_ids = sorted(c.get_neuron_idx2(n) for n in stimulus)
    out_ids = sorted(c.get_neuron_idx2(n) for n in observed)
    assert stim_ids == list(range(min(stim_ids), max(stim_ids) + 1))
    assert out_ids == list(range(min(out_ids), max(out_ids) + 1))
    reset(1)
    traces = model.simulation_single(
        c, [stim_ids], 2000 * b.Hz, 100 * b.ms, [out_ids], 1
    )
    voltage, time_ms = traces["state_v"][0], traces["state_t"][0]
    assert voltage.shape == (12, 1000) and np.isfinite(voltage).all()
    with (OUT / "voltage.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["time_ms"] + [c.neurons[i].name for i in out_ids])
        writer.writerows(zip(time_ms.tolist(), *voltage.tolist()))
    with (OUT / "spikes.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["observed_local_index", "time_ms"])
        writer.writerows(
            zip(traces["spike_i"][0].tolist(), traces["spike_t"][0].tolist())
        )
    save(
        "functional-checks.json",
        {
            "status": "passed_alternate_graph_scenario",
            "scope": "100 ms LIF response on explicitly alternate Codex v783, not orientation-map/paper reproduction",
            "neurons": len(c.neurons),
            "aggregated_edges": len(c.synapses),
            "raw_edge_rows": len(c.synapses_raw),
            "materialization": manifest["materialization"],
            "author_graph_identity": manifest["author_graph_identity"],
            "stimulated_ids": stimulus,
            "observed_ids": observed,
            "observation_selection": "12 strongest positive direct postsynaptic visual neighbours of six fixed L1/L2/L3 inputs, selected before simulation",
            "cases": cases,
            "repeat_seed_equal": True,
            "zero_drive_quiescent": True,
            "dt_ms": 0.1,
            "duration_ms": 100,
            "voltage_unit": "mV, simulated model voltage",
            "biological_validation": False,
        },
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), layout="constrained")
    for i in range(3):
        axes[0].plot(time_ms, voltage[i], label=c.neurons[out_ids[i]].name)
    axes[0].set(xlabel="Model time (ms)", ylabel="Simulated membrane voltage (mV)")
    axes[0].legend(fontsize=7)
    axes[1].scatter(traces["spike_t"][0], traces["spike_i"][0], marker="|", s=15)
    axes[1].set(
        xlabel="Model time (ms)", ylabel="Observed neuron index", ylim=(-0.5, 11.5)
    )
    fig.suptitle(
        "Short LIF response: explicit alternate Codex v783 graph\n12 monitored neurons; no orientation-map or biological validation"
    )
    for ext in ("png", "svg"):
        fig.savefig(OUT / ("lif-response." + ext), dpi=180)
    plt.close(fig)


def verify_replay():
    original = json.loads((OUT / "functional-checks.json").read_text())
    repeated = json.loads(
        Path("/work/replay-export/functional-checks.json").read_text()
    )
    assert original == repeated
    hashes = {}
    for name in ["voltage.csv", "spikes.csv"]:
        first = hashlib.sha256((OUT / name).read_bytes()).hexdigest()
        second = hashlib.sha256(
            (Path("/work/replay-export") / name).read_bytes()
        ).hexdigest()
        assert first == second
        hashes[name] = first
    save(
        "independent-replay.json",
        {
            "status": "passed",
            "separate_process": True,
            "repeat_content_equal": True,
            "csv_sha256": hashes,
        },
    )


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "smoke":
        smoke()
    elif len(sys.argv) == 2 and sys.argv[1] == "functional":
        functional()
    elif len(sys.argv) == 2 and sys.argv[1] == "verify":
        verify_replay()
    else:
        raise SystemExit("Use smoke or functional")
