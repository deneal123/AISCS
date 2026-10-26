"""Observe the pinned native full-graph/game loop; no trained-game claims."""

import csv
import gc
import hashlib
import importlib.metadata
import itertools
import json
import sys
import time
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

sys.path.insert(0, "/work/source")
from doom.engine import NeuralControls
from doom.game import Game, retinal_samples
from doom.native import NativeBrain

ROOT = Path("/work/source")
OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)
GRAPH = ROOT / "outputs/doom/malecns_v1/graph.npz"
MANIFEST = json.loads(GRAPH.with_name("manifest.json").read_text())


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n")
    print(name, json.dumps(value), flush=True)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def trace(seed, name, ticks=35, condition="intact"):
    brain = NativeBrain(GRAPH)
    assert brain.n == MANIFEST["neurons"] == 166700
    assert len(brain.post) == MANIFEST["edges"] == 25582938
    original_weight_hash = hashlib.sha256(brain.weight.tobytes()).hexdigest()
    if condition == "all_edges_disconnected":
        brain.weight.fill(0)
    controls = NeuralControls(MANIFEST["readouts"], mode="bci")
    game = Game(seed=seed, scenario="combat_survival", spectator=True)
    rows, counts, voltages = [], [], []
    started = time.perf_counter()
    try:
        for tick in range(ticks):
            if game.observation()["finished"]:
                # Original protocol keeps the brain when the game resets.
                previous = brain.cursor
                game.new_episode()
                assert brain.cursor == previous
            frame = game.pixels()
            assert frame.shape == (480, 640, 3) and frame.dtype == np.uint8
            if name == "seed-1" and tick in {0, ticks - 1}:
                Image.fromarray(frame).save(OUT / f"game-input-{tick:02d}.png")
            light = retinal_samples(frame, brain.uv)
            if condition == "blank_vision":
                light.fill(0)
            steps = round((tick + 1) * 10000 / 35) - brain.cursor
            c, wall = brain.step(light, steps * 0.1)
            assert c.dtype == np.int32 and c.shape == (brain.n,)
            assert (c >= 0).all()
            for state in [brain.v, brain.g, brain.drive, brain.luminance]:
                assert np.isfinite(state).all()
            action = controls.decode(c, steps * 0.1 / 1000)
            applied = dict(action)
            if condition == "controls_clamped":
                applied.update(turn=0.0, forward=0.0, attack=False)
            game.act(applied)
            assert abs(brain.sim_ms - (tick + 1) * 1000 / 35) <= 0.051
            rows.append(
                {
                    "tick": tick + 1,
                    "neural_ms": brain.sim_ms,
                    "interval_ms": steps * 0.1,
                    "population_spikes": int(c.sum(dtype=np.int64)),
                    "active_neurons": int(np.count_nonzero(c)),
                    "source_frame_sha256": hashlib.sha256(frame.tobytes()).hexdigest(),
                    "input_sha256": hashlib.sha256(light.tobytes()).hexdigest(),
                    "turn": applied["turn"],
                    "forward": applied["forward"],
                    "attack": applied["attack"],
                    "neural_wall_seconds": wall,
                    **{k: v for k, v in game.observation().items() if k != "tick"},
                }
            )
            counts.append(c)
            voltages.append(brain.v[[r["index"] for r in MANIFEST["readouts"]]].copy())
        weights_unchanged = (
            hashlib.sha256(brain.weight.tobytes()).hexdigest() == original_weight_hash
        )
        assert weights_unchanged == (condition != "all_edges_disconnected")
        # A game-only reset must not pretend to reset neural state.
        before = brain.v.copy()
        cursor = brain.cursor
        game.new_episode()
        np.testing.assert_array_equal(brain.v, before)
        assert brain.cursor == cursor and game.tick == 0
        matrix = np.asarray(counts, dtype=np.int32)
        times = np.array([r["neural_ms"] for r in rows])
        np.savez_compressed(
            OUT / (name + ".npz"),
            ids=brain.ids,
            counts=matrix,
            time_ms=times,
            readout_ids=np.array(
                [int(r["id"]) for r in MANIFEST["readouts"]], dtype=np.int64
            ),
            readout_voltage_mv=np.asarray(voltages),
            final_v_mv=brain.v,
            final_g_mv=brain.g,
        )
        with (OUT / (name + ".csv")).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        summary = {
            "name": name,
            "seed": seed,
            "condition": condition,
            "ticks": ticks,
            "model_ms": brain.sim_ms,
            "wall_seconds": time.perf_counter() - started,
            "events": int(matrix.sum(dtype=np.int64)),
            "active_neurons": int(np.count_nonzero(matrix.sum(axis=0))),
            "counts_sha256": hashlib.sha256(matrix.tobytes()).hexdigest(),
            "frames_sha256": hashlib.sha256(
                "".join(r["source_frame_sha256"] for r in rows).encode()
            ).hexdigest(),
            "actions_sha256": hashlib.sha256(
                json.dumps(
                    [[r[k] for k in ["turn", "forward", "attack"]] for r in rows]
                ).encode()
            ).hexdigest(),
            "weights_unchanged": weights_unchanged,
            "nonzero_action_ticks": sum(
                bool(r["turn"] or r["forward"] or r["attack"]) for r in rows
            ),
            "game_reset_preserves_neural_state": True,
            "game_assets": game.assets,
            "npz_sha256": digest(OUT / (name + ".npz")),
        }
        save(name + ".json", summary)
        return summary
    finally:
        game.close()
        del brain
        gc.collect()


def step_events():
    """A separate 20-ms white-input test resolves every discrete neural step."""
    brain = NativeBrain(GRAPH)
    events = []
    for tick in range(200):
        c, _ = brain.step(np.ones(len(brain.retina)), 0.1)
        assert np.all(c <= 1)
        indices = np.flatnonzero(c)
        events.append(np.c_[np.full(len(indices), tick, dtype=np.int32), indices])
    events = np.concatenate(events).astype(np.int32)
    np.savez_compressed(
        OUT / "discrete-events.npz",
        step=events[:, 0],
        neuron_index=events[:, 1],
        neuron_id=brain.ids[events[:, 1]],
        time_ms=(events[:, 0].astype(float) + 1) * 0.1,
    )
    assert len(events) == brain.total_spikes
    save(
        "discrete-events.json",
        {
            "events": len(events),
            "steps": 200,
            "dt_ms": 0.1,
            "stimulus": "constant white retinal input and author tonic lamina drive",
            "time_convention": "end of a discrete 0.1-ms update; no sub-step timing",
            "not_closed_loop": True,
            "note": "Frame-level CSV/NPZ contain counts per game interval, not individual spike times. This separate probe calls the same native kernel one step at a time.",
        },
    )


def plot():
    with np.load(OUT / "seed-1.npz") as a:
        matrix = a["counts"].astype(np.int64)
        times = a["time_ms"]
    # Bin all neurons by index. These bins do not denote anatomy.
    edges = np.linspace(0, matrix.shape[1], 129, dtype=int)
    binned = np.array(
        [matrix[:, lo:hi].sum(axis=1) for lo, hi in itertools.pairwise(edges)]
    )
    assert binned.sum() == matrix.sum()
    with (OUT / "seed-1.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    fig, axs = plt.subplots(3, 1, figsize=(11, 9), constrained_layout=True)
    image = axs[0].imshow(
        binned, aspect="auto", origin="lower", extent=[0, times[-1], 0, 128]
    )
    fig.colorbar(image, ax=axs[0], label="Spikes / bin / game interval")
    axs[0].set(
        ylabel="Neuron-index bins",
        title="DoomFly baseline: full retained MaleCNS graph, seed 1",
    )
    axs[1].plot(times, matrix.sum(axis=1))
    axs[1].set(
        ylabel="Population spike count",
        title="Counts per 28.5/28.6-ms interval; no biological rate validation",
    )
    for key in ["turn", "forward", "attack"]:
        axs[2].plot(
            times,
            [
                float(r[key] == "True") if key == "attack" else float(r[key])
                for r in rows
            ],
            label=key,
        )
    axs[2].legend()
    axs[2].set(
        xlabel="Model time (ms)",
        ylabel="Game control units",
        title="Fixed neural-to-button mapping; no learned survival claim",
    )
    for suffix in ["png", "svg"]:
        fig.savefig(OUT / ("neural-game-recordings." + suffix), dpi=160)
    plt.close(fig)


def main():
    results = [
        trace(seed, name)
        for seed, name in [
            (1, "seed-1"),
            (2, "seed-2"),
            (3, "seed-3"),
            (1, "seed-1-repeat"),
        ]
    ]
    for field in ["counts_sha256", "frames_sha256", "actions_sha256"]:
        assert results[0][field] == results[3][field], field
    for condition in ["blank_vision", "all_edges_disconnected", "controls_clamped"]:
        results.append(trace(1, condition, ticks=10, condition=condition))
    step_events()
    plot()
    save(
        "functional.json",
        {
            "passed": True,
            "graph": MANIFEST,
            "graph_sha256": digest(GRAPH),
            "runs": results,
            "same_seed_exact": True,
            "versions": {
                k: importlib.metadata.version(k)
                for k in ["numpy", "brian2", "vizdoom", "numba", "pyarrow"]
            },
            "limits": [
                "Retinal coordinates and neuron-to-button gains are inferred/chosen mappings",
                "One reconstructed male; no population/biological replication",
                "No validated nociceptive transduction, pain state, CAP or ECAP operator",
                "Experimental v6 learning checked only in software fixtures, not demonstrated by baseline runs",
            ],
        },
    )


if __name__ == "__main__":
    main()
