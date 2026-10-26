"""Exercise the unchanged Pugliese rate model; report solver failures before clipping."""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import diffrax
import hydra
import jax
import jax.numpy as jnp
import numpy as np
from omegaconf import OmegaConf

SOURCE = Path.cwd()
WORK = Path("/work")
OUT = WORK / "exports"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(SOURCE))
jax.config.update("jax_enable_x64", False)

from src.simulation import vnc_sim as model
from src.utils.sim_utils import load_wTable


def save(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            value.update(chunk)
    return value.hexdigest()


def configuration(seed=1):
    with hydra.initialize_config_dir(
        config_dir=str(SOURCE / "configs"), version_base=None
    ):
        cfg = hydra.compose(config_name="config")
    cfg.paths.data_dir = str(SOURCE / "data")
    cfg.paths.cwd_dir = str(SOURCE)
    cfg.paths.base_dir = str(WORK / "native-output")
    cfg.paths.save_dir = str(WORK / "native-output")
    cfg.paths.ckpt_dir = str(WORK / "native-output/ckpt")
    cfg.paths.fig_dir = str(WORK / "native-output/figures")
    cfg.paths.log_dir = str(WORK / "native-output/logs")
    cfg.experiment.n_replicates = 1
    cfg.experiment.seed = seed
    cfg.sim.rtol = 1e-4
    cfg.sim.atol = 1e-7
    return cfg


def smoke():
    cfg = configuration()
    table = load_wTable(cfg.experiment.dfPath)
    save(
        "smoke.json",
        {
            "status": "passed",
            "jax": jax.__version__,
            "diffrax": diffrax.__version__,
            "devices": [str(device) for device in jax.devices()],
            "neurons": len(table),
            "columns": list(table.columns),
            "source_model": "rectified half-tanh firing-rate ODE, not discrete spikes",
            "x64": bool(jax.config.jax_enable_x64),
        },
    )
    assert len(table) == 4604
    print("Imported native model and exact 4604-neuron tutorial table", flush=True)


def checkpoint_fixture():
    from src.data.data_classes import CheckpointState
    from src.memory.checkpointing import load_checkpoint, save_checkpoint

    signal = jnp.arange(24, dtype=jnp.float32).reshape(3, 8)
    state = CheckpointState(
        0,
        0,
        0,
        None,
        0,
        checkpoint_type="streaming",
        completed_simulations={0},
        results_dict={0: signal},
        failed_sims=set(),
        progress_info={"completed": 1},
    )
    path = WORK / "checkpoint-fixture/checkpoint.h5"
    save_checkpoint(state, path, metadata={"scope": "own serialization fixture"})
    loaded, _, metadata = load_checkpoint(path.parent / "results_checkpoint", path.stem)
    assert loaded.completed_simulations == {0}
    np.testing.assert_array_equal(loaded.results_dict[0], signal)
    assert metadata["scope"] == "own serialization fixture"
    return {
        "streaming_result_roundtrip_exact": True,
        "scope": "serialization fixture; not full campaign resume",
    }


def software():
    overrides = [
        "paths.base_dir=/work/config-demo",
        "paths.save_dir=/work/config-demo",
        "paths.log_dir=/work/config-demo/logs",
        "paths.data_dir=" + str(SOURCE / "data"),
        "paths.cwd_dir=" + str(SOURCE),
        "hydra.run.dir=/work/config-demo",
    ]
    process = subprocess.run(
        [sys.executable, "test_configs.py", *overrides],
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
        env=dict(os.environ, PYTHONPATH=str(SOURCE)),
    )
    (OUT / "native-config-demo.log").write_text(
        process.stdout + process.stderr, encoding="utf-8"
    )
    assert process.returncode == 0, process.stderr
    assert (WORK / "config-demo/logs/run_config.yaml").exists()
    cli = subprocess.run(
        [sys.executable, "src/run_hydra.py", "--help"],
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
        env=dict(os.environ, PYTHONPATH=str(SOURCE)),
    )
    (OUT / "native-cli-help.log").write_text(cli.stdout + cli.stderr, encoding="utf-8")
    assert cli.returncode == 0, cli.stderr
    # Independent analytical fixture for the source rate equation.
    rates = jnp.array([1.0, 2.0, 3.0])
    weights = jnp.array([[0.0, 2.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
    inputs = jnp.array([10.0, 0.0, 2.0])
    tau, a, threshold, cap = (
        jnp.ones(3) * 0.02,
        jnp.ones(3),
        jnp.ones(3),
        jnp.ones(3) * 200,
    )
    args = (
        inputs,
        0.02,
        0.9,
        tau,
        weights,
        threshold,
        a,
        cap,
        jax.random.PRNGKey(1),
        0.0,
    )
    actual = np.asarray(model.rate_equation_half_tanh(0.1, rates, args))
    expected = (
        np.maximum(
            200
            * np.tanh(
                (np.asarray(inputs) + np.asarray(weights) @ np.asarray(rates) - 1) / 200
            ),
            0,
        )
        - np.asarray(rates)
    ) / 0.02
    np.testing.assert_allclose(actual, expected, rtol=1e-6, atol=1e-5)
    changed_noise = (*args[:-2], jax.random.PRNGKey(99), 999.0)
    np.testing.assert_array_equal(
        actual, model.rate_equation_half_tanh(0.1, rates, changed_noise)
    )
    weighted = np.asarray(model.reweight_connectivity(weights, 0.03, 0.04))
    np.testing.assert_allclose(
        weighted,
        0.03 * np.maximum(np.asarray(weights).T, 0)
        + 0.04 * np.minimum(np.asarray(weights).T, 0),
    )
    save(
        "software.json",
        {
            "status": "passed",
            "native_suite": "absent; test_configs.py is a configuration demonstration",
            "native_config_demo_exit": process.returncode,
            "native_cli_help_exit": cli.returncode,
            "analytical_rate_equation_fixture": True,
            "weight_orientation_fixture": True,
            "input_noise_ignored_by_native_rate_equation": True,
            "checkpoint": checkpoint_fixture(),
        },
    )
    print(
        "Configuration demo, analytical equation and checkpoint serialization checked",
        flush=True,
    )


def prepare(cfg, table):
    params = model.prepare_neuron_params(cfg, table)
    sim = model.prepare_sim_params(cfg, len(params.input_currents), len(table))
    weights = model.reweight_connectivity(
        params.W * params.W_mask[0], sim.exc_multiplier, sim.inh_multiplier
    )
    args = (
        weights,
        params.tau[0],
        params.a[0],
        params.threshold[0],
        params.fr_cap[0],
        params.input_currents[0, 0],
        sim.noise_stdv,
        sim.t_axis,
        sim.T,
        sim.dt,
        sim.pulse_start,
        sim.pulse_end,
        sim.r_tol,
        sim.a_tol,
        params.seeds[0],
    )
    return params, sim, args


@jax.jit
def raw_solver(args):
    # Same native equation, initial state, solver, arguments, controller and max_steps.
    # This observer exposes information discarded by run_single_simulation.
    (
        weights,
        tau,
        a,
        threshold,
        cap,
        inputs,
        noise,
        axis,
        duration,
        dt,
        start,
        end,
        rtol,
        atol,
        key,
    ) = args
    return diffrax.diffeqsolve(
        diffrax.ODETerm(model.rate_equation_half_tanh),
        diffrax.Dopri5(),
        0,
        duration,
        dt,
        jnp.zeros(weights.shape[1]),
        args=(inputs, start, end, tau, weights, threshold, a, cap, key, noise),
        saveat=diffrax.SaveAt(ts=axis),
        stepsize_controller=diffrax.PIDController(rtol=rtol, atol=atol),
        max_steps=100000,
        throw=False,
    )


def run_case(name, cfg, table, inspect_raw=False):
    params, sim, args = prepare(cfg, table)
    started = time.monotonic()
    rate = np.asarray(model.run_single_simulation(*args))
    elapsed = time.monotonic() - started
    assert rate.shape == (len(table), len(sim.t_axis))
    assert np.isfinite(rate).all()
    assert (rate >= 0).all() and (rate <= 1000).all()
    path = OUT / (name + ".npz")
    np.savez_compressed(
        path, rates=rate, times=np.asarray(sim.t_axis), body_ids=table.bodyId.to_numpy()
    )
    np.testing.assert_array_equal(np.load(path)["rates"], rate)
    item = {
        "name": name,
        "seed": int(cfg.experiment.seed),
        "seconds": elapsed,
        "simulated_seconds": sim.T,
        "shape": list(rate.shape),
        "dtype": str(rate.dtype),
        "max_rate": float(rate.max()),
        "active_neurons": int(np.any(rate > 0.01, axis=1).sum()),
        "export": path.name,
        "sha256": sha(path),
        "array_sha256": hashlib.sha256(rate.tobytes()).hexdigest(),
        "rtol": float(cfg.sim.rtol),
        "atol": float(cfg.sim.atol),
        "raw_solver_checked": False,
    }
    if inspect_raw:
        raw = raw_solver(args)
        values = np.asarray(raw.ys).T
        raw_success = bool(raw.result == diffrax.RESULTS.successful)
        item["raw_solver"] = {
            "successful": raw_success,
            "result": str(raw.result),
            "stats": {key: int(value) for key, value in raw.stats.items()},
            "finite": bool(np.isfinite(values).all()),
            "negative_values": int((values < 0).sum()),
            "above_1000": int((values > 1000).sum()),
            "nan_count": int(np.isnan(values).sum()),
            "inf_count": int(np.isinf(values).sum()),
        }
        # Compare defined native sanitization, not merely finite returned data.
        cleaned = np.clip(np.where(np.isfinite(values), values, 0), 0, 1000)
        np.testing.assert_allclose(rate, cleaned, rtol=2e-5, atol=2e-4)
        item["raw_solver_checked"] = True
        assert raw_success and np.isfinite(values).all(), item["raw_solver"]
    print(json.dumps(item), flush=True)
    save(name + ".json", item)
    return rate, item, params


def full():
    cfg = configuration()
    table = load_wTable(cfg.experiment.dfPath)
    assert len(table) == 4604
    assert table.index.tolist() == list(range(len(table)))
    assert table.bodyId.is_unique
    matrix_path = Path(cfg.experiment.wPath)
    # Header and row IDs must match annotation order before numeric loading.
    import csv

    with matrix_path.open(newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader)
        row_ids = [int(row[0]) for row in reader]
    assert [int(value) for value in header[1:]] == table.index.tolist()
    assert row_ids == table.bodyId.tolist()
    (OUT / "configuration.yaml").write_text(
        OmegaConf.to_yaml(cfg, resolve=True), encoding="utf-8"
    )
    all_cases = []
    first = None
    for index, seed in enumerate([1, 2, 3, 1]):
        current = configuration(seed)
        name = f"baseline-seed-{seed}" + ("-repeat" if index == 3 else "")
        values, item, params = run_case(name, current, table, inspect_raw=index == 0)
        if index == 0:
            first = values
            np.savez_compressed(
                OUT / "seed-1-parameters.npz",
                tau=np.asarray(params.tau),
                a=np.asarray(params.a),
                threshold=np.asarray(params.threshold),
                fr_cap=np.asarray(params.fr_cap),
            )
        if index == 3:
            np.testing.assert_array_equal(values, first)
        all_cases.append(item)
        save("progress.json", all_cases)
    zero = configuration()
    zero.experiment.stimI = [[0]]
    values, item, _ = run_case("no-input", zero, table)
    assert not np.any(values)
    all_cases.append(item)
    removed = configuration()
    removed.experiment.removeNeurons = [31]
    values, item, params = run_case("stim-neuron-disconnected", removed, table)
    assert not np.asarray(params.W_mask[0])[31].any()
    assert not np.asarray(params.W_mask[0])[:, 31].any()
    assert np.any(
        values[31] > 0
    )  # Connectivity removal is not clamping the stimulated state.
    assert not np.any(values[np.arange(len(table)) != 31] > 0.01)
    all_cases.append(item)
    faster = configuration()
    faster.neuron_params.tauMean = 0.015
    values, item, _ = run_case("tau-15ms", faster, table)
    assert not np.array_equal(values, first)
    all_cases.append(item)
    strict = configuration()
    strict.sim.rtol, strict.sim.atol = 2e-6, 5e-9
    values, item, _ = run_case("paper-tolerance", strict, table, inspect_raw=True)
    item["difference_from_relaxed"] = {
        "rmse_model_rate": float(np.sqrt(np.mean((values - first) ** 2))),
        "max_absolute": float(np.max(np.abs(values - first))),
    }
    all_cases.append(item)
    save(
        "functional.json",
        {
            "status": "passed",
            "neurons": len(table),
            "cases": all_cases,
            "repeat_seed_1_exact": True,
            "body_id_order_verified": True,
            "units": {
                "time": "s",
                "rate": "model firing rate (native source labels Hz); no physiological calibration verified",
                "stimulus": "model input, not physical current calibration",
            },
            "scope": "MANC T1 DN-to-MN rate model, not whole animal, spikes, nociception or ECAP",
            "reset": "native run_single_simulation initializes all states to zero on every call",
            "silencing": "native removeNeurons removes incoming and outgoing connectivity, not the forced input or state",
            "input_noise": "native rate equation ignores noise_stdv and PRNG key for input noise",
        },
    )
    subprocess.run(
        [sys.executable, "/work/probes/pugliese_reader.py"], check=True, timeout=120
    )
    subprocess.run(
        [sys.executable, "/work/probes/pugliese_plot.py"], check=True, timeout=120
    )


if __name__ == "__main__":
    {"smoke": smoke, "software": software, "full": full}[sys.argv[1]]()
