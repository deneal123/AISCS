"""Exercise actual claude-fly modules; distinguish fixture, full graph and body."""

import hashlib
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, "/work/source")
from brain_body_bridge import BrainBodyBridge, BrainEngine, DNRateDecoder
from run_pytorch import DT, MODEL_PARAMS, TorchModel

OUT = Path("/work/export")
OUT.mkdir(exist_ok=True)


def seed_all(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def software():
    weights = (
        torch.sparse_coo_tensor([[1, 2, 3], [0, 1, 2]], [100.0] * 3, (4, 4))
        .coalesce()
        .to_sparse_csr()
    )
    model = TorchModel(1, 4, DT, MODEL_PARAMS, weights, device="cpu")
    traces = []
    with torch.no_grad():
        for seed in (1, 2, 3, 1):
            seed_all(seed)
            state = model.state_init()
            rates = torch.zeros(1, 4)
            rates[0, 0] = 200
            trace = []
            for _ in range(500):
                state = model(rates, *state)
                assert all(torch.isfinite(x).all() for x in state)
                trace.append(state[3].numpy().copy())
            traces.append(np.stack(trace))
        np.testing.assert_array_equal(traces[0], traces[3])
        state = model.state_init()
        for _ in range(100):
            state = model(torch.zeros(1, 4), *state)
            assert not state[2].any()
    decoder = DNRateDecoder()
    drive = BrainBodyBridge(decoder).compute_drive()
    assert drive.shape == (2,) and np.isfinite(drive).all()
    save(
        "software.json",
        {
            "status": "passed",
            "scope": "four-unit software fixture only",
            "repeat_seed_equal": True,
            "zero_drive_quiescent": True,
            "dt_ms": DT,
            "voltage_shape": list(traces[0].shape),
            "torch": torch.__version__,
            "numpy": np.__version__,
        },
    )


def brain(fresh=False):
    started = time.monotonic()
    manifest = json.loads(Path("/work/claude-inputs.json").read_text())
    weights_info = next(
        x for x in manifest["inputs"] if x["path"] == "data/plastic_weights.pt"
    )
    checkpoint = Path("/work/source/data/plastic_weights.pt")
    if not fresh and weights_info.get("status") != "verified":
        raise ValueError(
            "Pinned plastic weights unavailable; no silent fresh-model substitute"
        )
    original_sha = (
        hashlib.sha256(checkpoint.read_bytes()).hexdigest() if not fresh else None
    )
    selected = (
        OUT / "deliberately-absent-fresh-initialization.pt" if fresh else checkpoint
    )
    if fresh and selected.exists():
        raise ValueError("Fresh model path unexpectedly contains a previous checkpoint")
    engine = BrainEngine(device="cpu", plastic_path=str(selected))
    if not fresh:
        restored = torch.load(checkpoint, map_location="cpu", weights_only=True)
        assert restored.shape == engine._syn_vals.shape
        torch.testing.assert_close(engine._syn_vals, restored, rtol=0, atol=0)
    initial = engine._syn_vals.clone()
    indexes = list(engine.dn_indices.values())
    assert len(indexes) > 0
    traces, records = [], []
    for attempt, seed in enumerate((1, 2, 3, 1)):
        seed_all(seed)
        engine._syn_vals.copy_(initial)
        engine.state = engine.model.state_init()
        engine._spike_acc.zero_()
        engine._hebb_count = 0
        engine.set_stimulus("sugar")
        trace, spike_counts = [], []
        start = time.monotonic()
        for step in range(1000):
            spikes = engine.step()
            assert spikes.shape == (1, engine.num_neurons)
            if step % 100 == 0:
                assert all(torch.isfinite(x).all() for x in engine.state)
            trace.append(engine.state[3][0, indexes].numpy().copy())
            spike_counts.append(int(spikes.sum()))
        values = np.asarray(trace)
        assert np.isfinite(values).all()
        assert sum(spike_counts) > 0
        delta = float(torch.max(torch.abs(engine._syn_vals - initial)))
        assert torch.isfinite(engine._syn_vals).all()
        np.savez(
            OUT / f"brain-seed{seed}-attempt{attempt}.npz",
            voltage_mV=values,
            spike_count=np.asarray(spike_counts),
            dt_ms=DT,
        )
        traces.append((values, np.asarray(spike_counts)))
        records.append(
            {
                "seed": seed,
                "spikes": sum(spike_counts),
                "seconds": time.monotonic() - start,
                "max_weight_change": delta,
            }
        )
        print("full brain", records[-1], flush=True)
    for first, repeated in zip(traces[0], traces[3]):
        np.testing.assert_array_equal(first, repeated)
    engine._syn_vals.copy_(initial)
    engine.state = engine.model.state_init()
    engine._spike_acc.zero_()
    engine._hebb_count = 0
    engine.set_stimulus(None)
    for _ in range(100):
        assert not engine.step().any()
    if not fresh:
        assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == original_sha
    save(
        "brain.json",
        {
            "status": "passed",
            "scope": "pinned full v783 graph, CPU",
            "initialization": "author fresh-weights condition"
            if fresh
            else "restored pinned checkpoint",
            "pretrained_weights_reproduced": not fresh,
            "neurons": engine.num_neurons,
            "weights": engine._syn_vals.numel(),
            "dn_mapped": len(indexes),
            "observed_units": [
                {
                    "name": name,
                    "tensor_index": int(idx),
                    "flywire_id": int(engine.i2flyid[idx]),
                }
                for name, idx in engine.dn_indices.items()
            ],
            "voltage_shape": list(traces[0][0].shape),
            "dt_ms": DT,
            "steps_per_trial": 1000,
            "duration_ms": 1000 * DT,
            "repeat_seed_equal": True,
            "zero_drive_quiescent": True,
            "trials": records,
            "checkpoint_sha256": original_sha,
            "checkpoint_unchanged": None if fresh else True,
            "seconds_including_load": time.monotonic() - started,
            "biological_validation": False,
            "body_coupled": False,
        },
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(11, 6), constrained_layout=True)
    t = np.arange(1000) * DT
    axes[0].plot(t, traces[0][0][:, :4])
    axes[0].set_ylabel("Model voltage (mV)")
    axes[0].set_title(
        "Pinned claude-fly: selected descending units; sugar input, seed 1"
    )
    axes[1].plot(t, traces[0][1], linewidth=0.8)
    axes[1].set(xlabel="Neural model time (ms)", ylabel="Full graph spikes / step")
    for ext in ("png", "svg"):
        fig.savefig(OUT / ("full-brain." + ext), dpi=160)


if __name__ == "__main__":
    {"software": software, "brain": brain, "brain-fresh": lambda: brain(fresh=True)}[
        sys.argv[1]
    ]()
