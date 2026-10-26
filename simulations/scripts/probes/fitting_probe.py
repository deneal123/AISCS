"""Exercise actual fitting-model classes on the author's exact v630 data."""

import hashlib
import json
import runpy
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path.cwd()))
probe_argv = sys.argv[:]
try:
    # The author module parses CLI arguments at import time as well.
    sys.argv = ["drosophila_whole_brain_fitting.py"]
    module = runpy.run_path(
        "drosophila_whole_brain_fitting.py", run_name="fitting_evaluation"
    )
finally:
    sys.argv = probe_argv
brainstate, u, jax = (module[name] for name in ["brainstate", "u", "jax"])
brainstate.environ.set(dt=0.2 * u.ms)
OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n")


def population():
    pop = module["Population"]("630")
    brainstate.nn.init_all_states(pop)
    return pop


def software():
    pop = population()
    with brainstate.environ.context(t=0 * u.ms):
        values = pop.update(np.full(pop.varshape, 3, dtype=np.float32) * u.mV)
    assert np.isfinite(np.asarray(values)).all()
    before = np.asarray(pop.g.value.to_decimal(u.mV)).copy()
    assert (before > 0).all()
    pop.reset_state()
    after = np.asarray(pop.g.value.to_decimal(u.mV))
    assert np.array_equal(before, after)
    brainstate.nn.init_all_states(pop)
    assert not np.any(np.asarray(pop.g.value.to_decimal(u.mV)))
    ids = [str(pop.i2flyid[i]) for i in range(pop.n_neuron)]
    assert len(ids) == len(set(ids))
    save(
        "software.json",
        {
            "status": "passed",
            "native_suite": False,
            "nodes": pop.n_neuron,
            "ids_unique": True,
            "single_population_step_finite": True,
            "native_reset_clears_g": False,
            "native_init_all_clears_g": True,
            "scope": "Real author population, not a substitute graph; incomplete native reset is recorded rather than silently fixed",
        },
    )


def smoke():
    pop = population()
    archive = np.load(
        "data/spike_rates/ito_2017-10-26_1_spike_rate.npz", allow_pickle=False
    )
    rates, areas = archive["rates"], archive["areas"]
    assert rates.ndim == 2 and np.isfinite(rates).all()
    assert len(areas) == rates.shape[0]
    cli = subprocess.run(
        [sys.executable, "drosophila_whole_brain_fitting.py", "--help"],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    (OUT / "cli-help.log").write_text(cli.stdout + cli.stderr)
    assert cli.returncode == 0
    save(
        "smoke.json",
        {
            "status": "passed",
            "nodes": pop.n_neuron,
            "author_rates_shape": list(rates.shape),
            "author_area_count": len(areas),
            "cli_help_exit": cli.returncode,
            "data_note": "Author-provided rates array is not independently validated as recorded action-potential events",
        },
    )


def full():
    started = time.monotonic()
    brainstate.random.seed(1)
    network = module["FiringRateNetwork"](
        flywire_version="630", neural_activity_id="2017-10-26_1", seed=1, n_rank=20
    )
    n = network.pop.n_neuron
    ids = np.array([str(network.pop.i2flyid[i]) for i in range(n)])
    np.savez_compressed(OUT / "nodes.npz", ids=ids)
    cases = []
    for index, (seed, weight) in enumerate([(1, 5), (2, 5), (3, 5), (1, 5), (1, 0)]):
        brainstate.random.seed(seed)
        brainstate.nn.init_all_states(network)
        voltages, events = [], []
        step = brainstate.transform.jit(
            lambda i, drive=weight: network.update_test(i, drive * u.mV)
        )
        for tick in range(50):
            spikes = np.asarray(step(tick))
            voltage = np.asarray(network.pop.v.value.to_decimal(u.mV))
            assert spikes.shape == voltage.shape == (n,)
            assert np.isfinite(spikes).all() and np.isfinite(voltage).all()
            fired = np.flatnonzero(spikes > 0)
            events.extend((tick, int(node)) for node in fired)
            voltages.append(voltage.copy())
        states = np.stack(voltages)
        name = "seed-{}{}".format(
            seed, "-repeat" if index == 3 else "-no-input" if index == 4 else ""
        )
        path = OUT / (name + ".npz")
        np.savez_compressed(
            path,
            voltage_mV=states,
            times_ms=(np.arange(50) + 1) * 0.2,
            events=np.array(events, dtype=np.int64).reshape(-1, 2),
            ids=ids,
        )
        digest = hashlib.sha256(states.tobytes()).hexdigest()
        event_digest = hashlib.sha256(
            np.array(events, dtype=np.int64).reshape(-1, 2).tobytes()
        ).hexdigest()
        if index == 0:
            first = (digest, event_digest)
        if index == 3:
            assert first == (digest, event_digest)
        item = {
            "name": name,
            "seed": seed,
            "native_noise_weight_mV": weight,
            "steps": 50,
            "shape": list(states.shape),
            "events": len(events),
            "state_sha256": digest,
            "events_sha256": event_digest,
            "file": path.name,
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        cases.append(item)
        save(name + ".json", item)
        print(json.dumps(item), flush=True)
    rates = np.asarray(network.count_neuropil_fr(length=50).to_decimal(u.Hz))
    assert np.isfinite(rates).all()
    save(
        "functional.json",
        {
            "status": "passed",
            "nodes": n,
            "neuropils": network.neural_activity.n_neuropil,
            "author_timepoints": network.neural_activity.n_time,
            "cases": cases,
            "repeat_seed_equal": True,
            "seconds": time.monotonic() - started,
            "initialization": "native init_all_states each case; native reset_state alone leaves synaptic g",
            "clock": "state after 0.2-ms update; event integer tick is linked to output time (tick+1)*0.2 ms",
            "scope": "Original full v630 FiringRateNetwork and original sparse+LoRA interaction with untrained parameters; native Poisson input. No fitting stages, RNN training, paper accuracy, biology, nociception or CAP/ECAP reproduction claimed",
            "units": "nominal native ms/mV, not independent physiological calibration",
            "data_identity": "received author's exact SHA-pinned RAR; compatibility checked by actual constructors; no archive release tag asserted",
        },
    )
    subprocess.run(
        [sys.executable, "/work/probes/fitting_plot.py"], check=True, timeout=120
    )


if __name__ == "__main__":
    {"software": software, "smoke": smoke, "full": full}[sys.argv[1]]()
