"""Run the pinned Flyvis code and exact pretrained model on explicit recorded inputs."""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch

torch.set_num_threads(4)
torch.set_num_interop_threads(1)
OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(Path.cwd()))
import flyvis
from flyvis.network import NetworkView


def save(name, data):
    (OUT / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def smoke():
    view = NetworkView(flyvis.results_dir / "flow/0000/000")
    network = view.init_network()
    checkpoint = flyvis.results_dir / "flow/0000/000/chkpts/chkpt_00000"
    state = torch.load(checkpoint, map_location="cpu", weights_only=False)["network"]
    assert set(state) == set(network.state_dict())
    assert all(
        torch.equal(value.cpu(), network.state_dict()[key].cpu())
        for key, value in state.items()
    )
    cli = subprocess.run(
        ["/work/env/bin/flyvis", "--help"],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    (OUT / "native-cli-help.log").write_text(cli.stdout + cli.stderr)
    assert cli.returncode == 1 and "usage: flyvis" in cli.stdout
    specific = subprocess.run(
        ["/work/env/bin/flyvis", "download-pretrained", "--help"],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    (OUT / "native-cli-command-help.log").write_text(specific.stdout + specific.stderr)
    assert specific.returncode == 0, specific.stderr
    save(
        "smoke.json",
        {
            "status": "passed",
            "flyvis_version": flyvis.__version__,
            "torch_version": torch.__version__,
            "device": str(flyvis.device),
            "nodes": int(network.n_nodes),
            "edges": int(network.n_edges),
            "checkpoint_sha256": sha(checkpoint),
            "checkpoint_state_loaded_exact": True,
            "state_keys": sorted(state),
            "cli_help_exit": cli.returncode,
            "specific_command_help_exit": specific.returncode,
            "scope": "official trained optic-lobe model, not whole brain or physiological spikes",
        },
    )


def record(network, name, movie, dt=0.005):
    movie = torch.as_tensor(movie, dtype=torch.float32, device=flyvis.device)
    assert (
        movie.ndim == 4
        and movie.shape[0] == movie.shape[2] == 1
        and movie.shape[-1] == 721
    )
    assert torch.isfinite(movie).all()
    started = time.monotonic()
    with torch.no_grad():
        response = network.simulate(movie, dt=dt, initial_state="auto")
    values, inputs = response.detach().cpu().numpy(), movie.cpu().numpy()
    assert values.shape == (1, movie.shape[1], network.n_nodes)
    assert np.isfinite(values).all()
    path = OUT / (name + ".npz")
    np.savez_compressed(
        path,
        input=inputs,
        activity=values,
        times_s=(np.arange(movie.shape[1]) + 1) * dt,
        input_frame_start_s=np.arange(movie.shape[1]) * dt,
    )
    with np.load(path, allow_pickle=False) as data:
        np.testing.assert_array_equal(data["activity"], values)
        np.testing.assert_array_equal(data["input"], inputs)
    item = {
        "name": name,
        "seconds": time.monotonic() - started,
        "shape": list(values.shape),
        "input_shape": list(inputs.shape),
        "dt_s": dt,
        "clock_convention": "activity is recorded after the Euler update; input frame starts one dt earlier",
        "finite": True,
        "min_activity": float(values.min()),
        "max_activity": float(values.max()),
        "activity_array_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
        "input_array_sha256": hashlib.sha256(inputs.tobytes()).hexdigest(),
        "file": path.name,
        "sha256": sha(path),
    }
    print(json.dumps(item), flush=True)
    save(name + ".json", item)
    return values, item


def full():
    from flyvis.datasets.flashes import Flashes
    from flyvis.datasets.moving_bar import MovingEdge

    view = NetworkView(flyvis.results_dir / "flow/0000/000")
    network = view.init_network()
    network.eval()
    network.requires_grad_(False)
    assert (network.n_nodes, network.n_edges) == (45669, 1513231)
    original = {
        key: value.detach().clone() for key, value in network.state_dict().items()
    }
    types = network.connectome.nodes.type[:].astype(str)
    u, v = network.connectome.nodes.u[:], network.connectome.nodes.v[:]
    np.savez_compressed(
        OUT / "nodes.npz", index=np.arange(network.n_nodes), cell_type=types, u=u, v=v
    )
    cases = []
    baseline = None
    for i, seed in enumerate([1, 2, 3, 1]):
        movie = (
            np.random.default_rng(seed)
            .uniform(0, 1, (1, 20, 1, 721))
            .astype(np.float32)
        )
        name = f"noise-seed-{seed}" + ("-repeat" if i == 3 else "")
        values, item = record(network, name, movie)
        item["external_stimulus_seed"] = seed
        cases.append(item)
        if i == 0:
            baseline = values
        if i == 3:
            np.testing.assert_array_equal(values, baseline)
    for name, intensity in [("grey-input", 0.5), ("dark-input", 0.0)]:
        _, item = record(
            network, name, np.full((1, 20, 1, 721), intensity, dtype=np.float32)
        )
        cases.append(item)
    flashes = Flashes(radius=[-1], dt=0.005, t_pre=0.05, t_stim=0.05)
    assert len(flashes) == 2
    for i in range(len(flashes)):
        native = np.asarray(flashes[i].cpu())
        values, item = record(
            network, "native-flash-" + str(i), native[None, :, None, :]
        )
        item["native_stimulus"] = str(flashes.arg_df.iloc[i].to_dict())
        cases.append(item)
    from flyvis_render import install

    install()
    moving = MovingEdge(
        offsets=(-2, 3),
        intensities=[1],
        speeds=[100],
        height=9,
        angles=[0, 180],
        t_pre=0.02,
        t_post=0.02,
        dt=0.005,
    )
    selected = []
    for i in range(min(2, len(moving))):
        sample = moving[i]
        if isinstance(sample, dict):
            sample = sample["lum"]
        native = np.asarray(sample.cpu())
        # Native moving stimuli may have NaN padding after the real trajectory.
        # Keep contiguous complete leading frames and record their count explicitly.
        valid = np.isfinite(native).all(axis=-1)
        length = int(np.flatnonzero(~valid)[0]) if not valid.all() else len(native)
        assert length > 0 and not valid[length:].any()
        movie = native[:length][None, :, None, :]
        selected.append(movie)
        values, item = record(network, "native-moving-edge-" + str(i), movie)
        item["native_padding_removed_frames"] = len(native) - length
        cases.append(item)
    assert selected
    with torch.no_grad():
        network.edges_syn_strength.zero_()
    _, item = record(network, "zero-synaptic-strength", selected[0])
    item["control"] = (
        "all learned synaptic strengths zero; biases and time constants preserved"
    )
    cases.append(item)
    network.load_state_dict(original, strict=True)
    indices = np.flatnonzero(types == "T4a")
    assert len(indices) > 0

    def clamp_t4a(state):
        state.nodes.activity[:, indices] = 0
        return state

    network.register_state_hook(clamp_t4a)
    suppressed, item = record(network, "T4a-state-clamp", selected[0])
    assert not np.any(suppressed[:, :, indices])
    item["control"] = (
        "native state-hook API clamps all T4a activities to zero, including initialization"
    )
    item["clamped_nodes"] = indices.tolist()
    cases.append(item)
    network.clear_state_hooks()
    restored, item = record(network, "restored-moving-edge", selected[0])
    reference = np.load(OUT / "native-moving-edge-0.npz")["activity"]
    np.testing.assert_array_equal(restored, reference)
    cases.append(item)
    assert all(
        torch.equal(value, network.state_dict()[key]) for key, value in original.items()
    )
    save(
        "functional.json",
        {
            "status": "passed",
            "nodes": int(network.n_nodes),
            "edges": int(network.n_edges),
            "cases": cases,
            "repeat_seed_equal": True,
            "restored_state_equal": True,
            "model_parameters_restored_exact": True,
            "seed_role": "external random stimulus; fixed official pretrained parameters",
            "initialization": "native simulate(auto): one second of grey-input steady state for each scenario",
            "time_unit": "native model seconds at dt=.005; physical response calibration not independently established",
            "state_unit": "native DMN activity, not recorded action-potential events or CAP",
            "node_identity": "cell_type and retinotopic u,v; these are model nodes, not FlyWire root IDs",
        },
    )
    subprocess.run(
        [sys.executable, "/work/probes/flyvis_plot.py"], check=True, timeout=120
    )


if __name__ == "__main__":
    {"smoke": smoke, "full": full}[sys.argv[1]]()
