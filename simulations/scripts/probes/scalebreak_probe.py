"""Run native retinal generation, pretrained responses and bounded controls."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

BASE = Path("/work/source/scalebreak_flyvis")
OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(BASE / "src"))
COMMANDS = []
DT = 0.005  # Native script default; the earlier 0.01 trial is retained separately.


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    if name == "commands.json":
        print(name, len(obj), "commands; latest exit", obj[-1]["exit_code"], flush=True)
    else:
        print(name, json.dumps(obj), flush=True)


def module(name):
    spec = importlib.util.spec_from_file_location(
        "probe_" + name, BASE / "scripts" / (name + ".py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def cli(name, args, label):
    command = [
        sys.executable,
        "-u",
        str(BASE / "scripts" / (name + ".py")),
        *map(str, args),
    ]
    started = time.monotonic()
    with (OUT / (label + ".log")).open("w") as stream:
        status = subprocess.run(
            command, stdout=stream, stderr=subprocess.STDOUT, check=False
        ).returncode
    COMMANDS.append(
        {
            "command": command,
            "log": label + ".log",
            "exit_code": status,
            "seconds": time.monotonic() - started,
        }
    )
    save("commands.json", COMMANDS)
    if status:
        raise RuntimeError("Native command failed; see " + label + ".log")


def full():
    started = time.monotonic()
    manifest = json.loads(Path("/work/pretrained-inputs.json").read_text())
    root = Path(os.environ["FLYVIS_ROOT_DIR"])
    if root != Path("/tmp/aspa-flyvis"):
        raise ValueError("Model cache must stay in the owned disposable container")
    for item in manifest["files"]:
        source = Path("/work") / item["destination"]
        assert sha(source) == item["sha256"]
        target = root / item["member"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    import flyvis
    from flyvis.network import NetworkView

    view = NetworkView(flyvis.results_dir / manifest["model"])
    network = view.init_network()
    checkpoint = root / "results/flow/0000/000/chkpts/chkpt_00000"
    state = torch.load(checkpoint, map_location="cpu", weights_only=False)["network"]
    assert set(state) == set(network.state_dict())
    assert all(
        torch.equal(value.cpu(), network.state_dict()[key].cpu())
        for key, value in state.items()
    )
    save(
        "checkpoint-check.json",
        {
            "checkpoint_sha256": sha(checkpoint),
            "loaded_state_exact": True,
            "state_keys": sorted(state),
            "nodes": int(network.n_nodes),
            "edges": int(network.n_edges),
            "flyvis_version": flyvis.__version__,
            "torch_version": torch.__version__,
        },
    )
    del network
    gen = module("11_generate_flyvis_native_stimuli")
    analysis = module("13_analyze_flyvis_pilot_v2")
    checks = module("42_validate_unique_conditions")
    perturb = module("44_direct_flyvis_perturbations")
    runs = []
    first_stimulus = first_response = None
    for number, seed in enumerate((1, 2, 3, 1)):
        directory = OUT / f"run-{number}-seed-{seed}"
        stim, response = directory / "stimuli", directory / "responses"
        cli(
            "11_generate_flyvis_native_stimuli",
            [
                "--flyvis-root",
                root,
                "--out-dir",
                stim,
                "--scales",
                "3,6,9",
                "--angles",
                "0,90",
                "--contrasts",
                "1",
                "--repeats",
                "2",
                "--seed",
                seed,
                "--n-frames",
                "12",
                "--dt",
                str(DT),
                "--t-pre",
                ".02",
                "--active-frames",
                "8",
            ],
            f"generate-{number}",
        )
        cli(
            "12_run_flyvis_pilot_v2",
            [
                "--flyvis-root",
                root,
                "--stim-dir",
                stim,
                "--out-dir",
                response,
                "--batch-size",
                "1",
                "--device",
                "cpu",
            ],
            f"responses-{number}",
        )
        movies = np.load(stim / "stimuli.npy", mmap_mode="r")
        values = np.load(response / "flyvis_central_cell_responses.npy", mmap_mode="r")
        meta = pd.read_csv(response / "metadata.csv")
        assert movies.shape == (66, 12, 1, 721)
        assert values.shape[:2] == (66, 12) and np.isfinite(values).all()
        assert np.isfinite(movies).all() and movies.min() >= 0 and movies.max() <= 1
        coordinates = pd.read_csv(stim / "hex_coordinates.csv")
        projection = [checks.projection_summary(coordinates, size) for size in (24, 32)]
        assert projection[1]["n_sample_collisions"] == 0
        # Explicitly test geometry with nuisance/noise held fixed, not by nominal labels.
        x, y = coordinates.x.to_numpy(), coordinates.y.to_numpy()
        edge_small, _ = gen.render_movie("moving_edge", "edge", 3, 0, 1, x, y, 12, 2, 8)
        edge_large, _ = gen.render_movie("moving_edge", "edge", 9, 0, 1, x, y, 12, 2, 8)
        assert np.array_equal(edge_small, edge_large)
        groups = meta.groupby(
            ["feature_family", "shape", "scale", "angle", "contrast"], dropna=False
        )
        duplicate_conditions = 0
        for _, group in groups:
            ids = group["sample"].to_numpy(dtype=int)
            duplicate_conditions += int(np.array_equal(movies[ids[0]], movies[ids[1]]))
        assert duplicate_conditions == 0
        features = analysis.response_features(
            np.asarray(values), t_pre_frames=round(0.02 / DT), bins=3
        )
        assert all(np.isfinite(x).all() for x in features.values())
        subset = meta.feature_family.isin(
            ["moving_bar", "small_translating_target"]
        ).to_numpy()
        scores = analysis.scale_generalization(
            features["temporal_bins"], meta, "direction", subset=subset, seed=seed
        )
        assert len(scores) > 0 and scores.accuracy.notna().all()
        scores.to_csv(directory / "diagnostic-scale-generalization.csv", index=False)
        record = {
            "seed": seed,
            "stimulus_shape": list(movies.shape),
            "response_shape": list(values.shape),
            "stimulus_sha256": sha(stim / "stimuli.npy"),
            "response_sha256": sha(response / "flyvis_central_cell_responses.npy"),
            "repeat_pairs_identical": duplicate_conditions,
            "edge_scale_neutral_verified": True,
            "projections": projection,
            "features": {k: list(v.shape) for k, v in features.items()},
            "diagnostic_score_rows": len(scores),
        }
        runs.append(record)
        if number == 0:
            first_stimulus = np.asarray(movies[0:1]).copy()
            first_response = np.asarray(values[0:1]).copy()
        print("completed seed", seed, "run", number, flush=True)
    assert runs[0]["stimulus_sha256"] == runs[3]["stimulus_sha256"]
    assert runs[0]["response_sha256"] == runs[3]["response_sha256"]
    assert len({x["stimulus_sha256"] for x in runs[:3]}) == 3
    interventions = []
    for variant in (
        "full",
        "t4t5_state_silencing",
        "spatial_kernel_shuffle",
        "type_pair_strength_shuffle",
    ):
        # NetworkView caches its network; a fresh view keeps state hooks from
        # a preceding intervention out of the next condition.
        fresh_view = NetworkView(flyvis.results_dir / manifest["model"])
        network = fresh_view.init_network()
        assert not network._state_hooks
        assert all(
            torch.equal(value.cpu(), network.state_dict()[key].cpu())
            for key, value in state.items()
        )
        info = perturb.apply_perturbation(network, variant, seed=1)
        initial = network.steady_state(1, DT, batch_size=1, value=0.5)
        values = (
            network.simulate(torch.tensor(first_stimulus), dt=DT, initial_state=initial)
            .detach()
            .cpu()
            .numpy()
        )
        finite = bool(np.isfinite(values).all())
        nonfinite = int(np.count_nonzero(~np.isfinite(values)))
        if variant == "t4t5_state_silencing":
            types = network.connectome.nodes.type[:].astype(str)
            selected = np.flatnonzero(
                np.char.startswith(types, "T4") | np.char.startswith(types, "T5")
            )
            assert np.all(values[:, :, selected] == 0)
        central = values[:, :, view.connectome.central_cells_index[:]]
        if variant == "full":
            assert np.array_equal(central, first_response)
        np.save(OUT / ("perturb-" + variant + ".npy"), central, allow_pickle=False)
        interventions.append(
            dict(
                info,
                response_shape=list(central.shape),
                finite=finite,
                nonfinite_all_node_values=nonfinite,
                fresh_view=True,
                initial_parameters_match_checkpoint=True,
            )
        )
        save("interventions.json", interventions)
        del network
    finer_checks = []
    for failed in (item for item in interventions if not item["finite"]):
        finer_view = NetworkView(flyvis.results_dir / manifest["model"])
        network = finer_view.init_network()
        perturb.apply_perturbation(network, failed["variant"], seed=1)
        initial = network.steady_state(1, DT / 2, batch_size=1, value=0.5)
        value = (
            network.simulate(
                torch.tensor(np.repeat(first_stimulus, 2, axis=1)),
                dt=DT / 2,
                initial_state=initial,
            )
            .detach()
            .cpu()
            .numpy()
        )
        np.save(
            OUT / ("finer-" + failed["variant"] + ".npy"),
            value[:, :, finer_view.connectome.central_cells_index[:]],
            allow_pickle=False,
        )
        finer_checks.append(
            {
                "variant": failed["variant"],
                "dt_seconds": DT / 2,
                "same_physical_input_duration": True,
                "finite": bool(np.isfinite(value).all()),
                "nonfinite_all_node_values": int(np.count_nonzero(~np.isfinite(value))),
            }
        )
        del network
    save(
        "functional.json",
        {
            "scope": "bounded pretrained model pipeline; not published performance reproduction",
            "model": manifest["model"],
            "runs": runs,
            "repeat_equal": True,
            "interventions": interventions,
            "finer_step_diagnostics": finer_checks,
            "status": "passed"
            if all(x["finite"] for x in interventions)
            else "partial",
            "seconds": time.monotonic() - started,
            "units": {
                "dt_seconds": DT,
                "scale": "retinal geometry units, not physical distance",
                "response": "FlyVis model activity, not spikes/mV/ECAP",
            },
            "not_verified": [
                "published full-grid results and ensembles",
                "biological functional validation",
                "cross-species transfer, nociception, pain, ECAP",
            ],
            "score_limit": "Tiny synthetic diagnostic grid; decoder scores are not estimates of generalization for the published study",
        },
    )
    if not all(x["finite"] for x in interventions):
        raise RuntimeError(
            "At least one native-step intervention produced nonfinite values; raw exports retained"
        )


if __name__ == "__main__":
    full()
