"""Exercise actual Eon modules and full v783 CLI; do not infer biological validity."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import runpy
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch

SOURCE = Path("/work/source")
EXPORT = Path("/work/exports/eon")
sys.path.insert(0, str(SOURCE / "code"))
import benchmark
import run_pytorch as upstream


def seed_all(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def fixture():
    """A software fixture, explicitly distinct from the registered whole graph."""
    weights = (
        torch.sparse_coo_tensor(
            torch.tensor([[1, 2, 3, 4, 5, 6, 7], [0, 1, 2, 3, 4, 5, 6]]),
            torch.full((7,), 100.0),
            (8, 8),
        )
        .coalesce()
        .to_sparse_csr()
    )
    model = upstream.TorchModel(
        1,
        8,
        upstream.DT,
        upstream.MODEL_PARAMS,
        weights,
        exc_indices=[0],
        device="cpu",
    )
    trials = []
    arrays = []
    for attempt, seed in enumerate((1, 2, 3, 1)):
        seed_all(seed)
        state = model.state_init()
        rates = torch.zeros(1, 8)
        rates[:, 0] = 200.0
        spikes, voltages = [], []
        with torch.no_grad():
            for _ in range(400):
                state = model(rates, *state)
                assert all(torch.isfinite(x).all() for x in state)
                assert state[2].shape == (1, 8)
                spikes.append(state[2].numpy().copy())
                voltages.append(state[3].numpy().copy())
        values = np.stack(spikes)
        assert values.sum() > 0
        arrays.append(values)
        path = EXPORT / f"fixture-seed{seed}-attempt{attempt}.npz"
        np.savez(path, spikes=values, voltage_mV=np.stack(voltages))
        trials.append(
            {
                "seed": seed,
                "spikes": int(values.sum()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    np.testing.assert_array_equal(arrays[0], arrays[3])
    state = model.state_init()
    with torch.no_grad():
        for _ in range(400):
            state = model(torch.zeros(1, 8), *state)
            assert state[2].sum() == 0
    return {
        "scope": "8-neuron software fixture, not a biological graph",
        "seeds": trials,
        "repeat_seed_equal": True,
        "state_reset_equal": True,
        "zero_input_quiescent": True,
        "dt_ms": upstream.DT,
        "voltage_unit": "mV",
        "trainable_parameters_in_default_model": sum(
            p.numel() for p in model.parameters() if p.requires_grad
        ),
        "runner_controls": runner_controls(),
    }


def runner_controls():
    """Test exposed experiment fields against the unmodified PyTorch runner."""
    directory = EXPORT / "control-fixture"
    directory.mkdir(exist_ok=True)
    ids = np.arange(100, 108)
    comp = directory / "completeness.csv"
    con = directory / "connectivity.parquet"
    pd.DataFrame({"label": ["fixture"] * 8}, index=ids).to_csv(comp)
    pd.DataFrame(
        {
            "Presynaptic_Index": np.arange(7),
            "Postsynaptic_Index": np.arange(1, 8),
            "Excitatory x Connectivity": np.full(7, 100.0),
        }
    ).to_parquet(con)
    upstream.path_comp, upstream.path_con, upstream.path_wt = comp, con, directory
    logger = benchmark.BenchmarkLogger()
    results = []
    arrays = []
    for label, first, second, silent in [
        ("stimulated", [100], [], []),
        ("silencing_requested", [100], [], ids.tolist()),
        ("second_population_only", [], [100], []),
    ]:
        seed_all(1)
        result = upstream.run_single_benchmark(
            0.04,
            1,
            {
                "key": label,
                "name": label,
                "neu_exc": first,
                "neu_exc2": second,
                "neu_slnc": silent,
                "stim_rate": 200.0,
            },
            logger,
            run_label="software_control_" + label,
            round_idx=1,
        )
        assert result["status"] == "success", result
        data = pd.read_parquet(result["spike_path"])
        arrays.append(data[["trial", "neuron_index", "time_ms"]])
        results.append(
            {"request": label, "spikes": len(data), "path": result["spike_path"]}
        )
    assert len(arrays[0]) > 0
    same = arrays[0].equals(arrays[1])
    brian_result = brian_runtime_fixture(comp, con)
    return {
        "scope": "8-neuron control fixture; upstream runner unchanged",
        "scenarios": results,
        "silencing_request_has_effect": not same,
        "second_population_only_produces_spikes": bool(len(arrays[2])),
        "brian_runtime_fixture": brian_result,
        "interpretation": "A request field is supported only if applied by the backend; "
        "the observed limitations are not repaired in this upstream run",
    }


def brian_runtime_fixture(comp, con):
    import brian2
    import run_brian2_cuda as brian_upstream

    brian2.prefs.codegen.target = "numpy"
    brian2.seed(1)
    params = dict(brian_upstream.default_params, t_run=40 * brian2.ms)
    try:
        spikes = brian_upstream._run_trial_cpu([0], [], [], str(comp), str(con), params)
        return {
            "status": "passed",
            "scope": "8-neuron runtime fixture, not C++ or full graph",
            "spikes": sum(len(x) for x in spikes.values()),
            "brian2": brian2.__version__,
        }
    except (brian2.core.base.BrianObjectException, KeyError, ValueError, RuntimeError):
        return {
            "status": "failed",
            "scope": "unmodified 8-neuron Brian2 runtime fixture",
            "traceback": traceback.format_exc(),
            "brian2": brian2.__version__,
            "changes_to_upstream": False,
        }


def full_graph():
    completeness = pd.read_csv(benchmark.path_comp, index_col=0)
    metadata = pq.ParquetFile(benchmark.path_con)
    n = len(completeness)
    columns = metadata.schema_arrow.names
    required = {"Presynaptic_Index", "Postsynaptic_Index", "Excitatory x Connectivity"}
    assert required <= set(columns)
    edge_count = 0
    for batch in metadata.iter_batches(columns=sorted(required), batch_size=500000):
        frame = batch.to_pandas()
        for column in ("Presynaptic_Index", "Postsynaptic_Index"):
            values = frame[column].to_numpy()
            assert (
                np.isfinite(values).all() and (values >= 0).all() and (values < n).all()
            )
            assert np.equal(values, np.floor(values)).all()
        assert np.isfinite(frame["Excitatory x Connectivity"].to_numpy()).all()
        edge_count += len(frame)
    assert edge_count == metadata.metadata.num_rows
    trials = []
    previous = None
    finite_checks = {"steps": 0, "state_tensor_values": 0}
    original_forward = upstream.TorchModel.forward

    def checked_forward(self, *args, **kwargs):
        state = original_forward(self, *args, **kwargs)
        for value in state:
            assert torch.isfinite(value).all(), "Non-finite full-graph state"
            finite_checks["state_tensor_values"] += value.numel()
        finite_checks["steps"] += 1
        return state

    # Diagnostics inspect returned state without changing any computed value.
    # Their overhead is included in the measured runtime and is disclosed below.
    upstream.TorchModel.forward = checked_forward
    # Seed injection only; the benchmark implementation and full input graph are unchanged.
    for attempt, seed in enumerate((1, 2, 3, 1)):
        seed_all(seed)
        label = f"evaluation_seed{seed}_attempt{attempt}"
        sys.argv = [
            str(SOURCE / "main.py"),
            "--pytorch",
            "--t_run",
            "0.1",
            "--n_run",
            "1",
            "--rounds",
            "1",
            "--run-label",
            label,
            "--no_log_file",
        ]
        runpy.run_path(str(SOURCE / "main.py"), run_name="__main__")
        rows = pd.read_csv(benchmark.csv_path)
        row = rows[rows.run_label == label].iloc[-1]
        assert row["status"] == "success", row.to_dict()
        path = Path(row["spike_path"])
        assert path.is_file()
        data = pd.read_parquet(path)
        assert len(data) > 0 and len(data) == int(row["spikes"])
        assert np.isfinite(data[["time_ms", "t", "neuron_index", "trial"]]).all().all()
        assert (data.time_ms >= 0).all() and (data.time_ms < 100.0).all()
        assert data.neuron_index.between(0, n - 1).all() and (data.trial == 0).all()
        ids = completeness.index.to_numpy()[data.neuron_index.to_numpy().astype(int)]
        np.testing.assert_array_equal(ids, data.flywire_id.to_numpy())
        values = data[["trial", "neuron_index", "time_ms", "flywire_id"]].reset_index(
            drop=True
        )
        if attempt == 0:
            previous = values
        if attempt == 3:
            pd.testing.assert_frame_equal(previous, values, check_exact=True)
        trials.append(
            {
                "seed": seed,
                "spikes": len(data),
                "active_neurons": data.flywire_id.nunique(),
                "simulation_seconds": float(row["sim_time"]),
                "setup_seconds": float(row["setup_time"]),
                "export_bytes": path.stat().st_size,
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return {
        "scope": "actual upstream PyTorch CLI, full registered FlyWire v783",
        "neurons": n,
        "connectivity_rows": edge_count,
        "trials": trials,
        "dt_ms": upstream.DT,
        "duration_ms": 100,
        "repeat_seed_equal": True,
        "ids_verified": True,
        "seed_injection": "numpy/random/torch before unchanged main.py",
        "finite_state_checks": finite_checks,
        "runtime_scope": "CPU simulation plus per-step finite-state diagnostics; not a bare benchmark",
        "limitations": [
            "No body or environment",
            "No human ECAP operator",
            "No biological validation inferred",
            "GPU not tested",
            "Silencing and second input population are not applied by this PyTorch runner",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["software", "full"])
    args = parser.parse_args()
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    EXPORT.mkdir(parents=True, exist_ok=True)
    result = fixture() if args.mode == "software" else full_graph()
    result.update(status="passed", torch=torch.__version__, numpy=np.__version__)
    (EXPORT / (args.mode + "-result.json")).write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
