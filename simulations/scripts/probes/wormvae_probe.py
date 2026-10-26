"""Exercise the original worm loaders and untrained dynamics in the legacy CPU environment."""

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path.cwd()))
from cnctm.nn import leaky_integrator_conductance, leaky_integrator_current
from cnctm.utils.data import ConnectomeConstructor
from model import WhiteConnectomeData, Worm_Data_Loader

torch.set_num_threads(4)
OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n")


def inputs():
    return WhiteConnectomeData(
        "data/worm_connectivity/", device="cpu"
    ), Worm_Data_Loader("data/worm_activity/")


def smoke():
    graph, data = inputs()
    assert len(graph.name_neuron_dict) == graph.N
    assert data.activity_worms.shape == (21, 189, 800)
    assert data.odor_worms.shape == (21, 3, 800)
    assert len(data.neuron_names) == 189 and data.step == 0.25
    for values in graph.synapses_dict.values():
        assert values.shape == (graph.N, graph.N) and torch.isfinite(values).all()
    cli = subprocess.run(  # noqa: UP022 -- pinned Python 3.6 has no capture_output
        [sys.executable, "main.py", "--help"],
        cwd="experiment",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=90,
    )
    (OUT / "original-cli-help.log").write_text(
        (cli.stdout + cli.stderr).decode("utf-8", errors="replace")
    )
    assert cli.returncode == 0 and b"--model_type" in cli.stdout
    save(
        "smoke.json",
        {
            "status": "passed",
            "nodes": graph.N,
            "activity_shape": list(data.activity_worms.shape),
            "odor_shape": list(data.odor_worms.shape),
            "missing_activity_values": int(np.isnan(data.activity_worms).sum()),
            "cli_exit": cli.returncode,
            "cli_limitation": "Two documented work-copy global tensor defaults changed to CPU; full training still contains explicit .cuda() paths and was not exercised",
            "torch": torch.__version__,
            "numpy": np.__version__,
            "python": sys.version,
        },
    )


def software():
    graph, data = inputs()
    target = torch.from_numpy(data.activity_worms[:1]).float()
    full = graph.make_full_connectome_activity(target, data.neuron_names)
    held = graph.make_full_connectome_activity(
        target, data.neuron_names, holdout_list=[data.neuron_names[0]]
    )
    index = graph.name_neuron_dict[data.neuron_names[0]].index
    assert torch.isnan(held[:, index]).all()
    assert torch.isfinite(full[:, index]).any()
    path = OUT / "native-connectome.pickle"
    graph.save_connectome_as_pickle(str(path))
    # The native constructor implements explicit current/conductance constraints;
    # a selected API check is distinguished from an absent author test suite.
    adjacency, weights = (
        graph.synapses_dict["chem_adj"],
        graph.synapses_dict["chem_weights"],
    )
    assert ((adjacency == 0) | (adjacency == 1)).all() and (weights >= 0).all()
    assert (adjacency[weights > 0] == 1).all()
    np.savez_compressed(
        str(OUT / "recorded-inputs.npz"),
        fluorescence=data.activity_worms,
        odors=data.odor_worms,
        names=np.array(data.neuron_names),
        step_s=np.array(data.step),
    )
    save(
        "software.json",
        {
            "status": "passed",
            "native_suite": False,
            "checks": [
                "real 21-worm fluorescence loader",
                "real odor loader",
                "real connectome weights",
                "native full-neuron mapping",
                "held-out neuron mask",
                "native pickle export",
            ],
            "nodes": graph.N,
            "masked_zero_count_connections": int(
                ((adjacency > 0) & (weights == 0)).sum()
            ),
            "zero_count_note": "Native source table contains zero-count rows; structural mask is not identical to positive-count support",
            "missing_not_imputed_as_measurements": True,
        },
    )


def model(graph, seed, kind, constraint):
    torch.manual_seed(seed)
    np.random.seed(seed)
    cn = ConnectomeConstructor(
        {
            "n": graph.N,
            "sparsity_c": graph.synapses_dict["chem_adj"],
            "sparsity_e": graph.synapses_dict["esym_adj"],
            "magnitudes_c": graph.synapses_dict["chem_weights"],
            "magnitudes_e": graph.synapses_dict["eassym_weights"],
            "signs_c": torch.ones(graph.N, graph.N),
        }
    )
    cls = (
        leaky_integrator_current if kind == "current" else leaky_integrator_conductance
    )
    return cls(
        cn,
        dt=0.00625,
        bias_init=torch.full((1, graph.N), 0.001),
        tau_init=torch.full((1, graph.N), 0.05),
        constraint=constraint,
    )


def rollout(graph, network, stimulus, zero_weights=False):
    # The native forward accepts lagged states. At each step its final sample
    # applies exactly one update to the last recorded state, not a fitted voltage.
    if zero_weights:
        with torch.no_grad():
            network.magnitudes_c.zero_()
            network.magnitudes_e.zero_()
    previous = torch.zeros(1, graph.N)
    rows = [previous.numpy().copy()]
    with torch.no_grad():
        for tick in range(100):
            hidden = torch.stack((previous, previous), dim=2)
            external = torch.zeros_like(hidden)
            if 20 <= tick < 60:
                external[:, :, -1] = stimulus * graph.neuron_mask_dict["sensory"]
            values, chem, electric = network(external, hidden, is_Training=False)
            previous = values[:, :, -1]
            assert all(torch.isfinite(x).all() for x in [previous, chem, electric])
            rows.append(previous.numpy().copy())
    return np.concatenate(rows, axis=0)


def full():
    graph, _ = inputs()
    cases = []
    names = [neuron.name for neuron in graph.neuron_list]
    for kind, constraint in [
        ("conductance", "weight"),
        ("conductance", "sparsity"),
        ("conductance", "unconstrained"),
        ("current", "sparsity"),
        ("current", "unconstrained"),
    ]:
        for index, seed in enumerate([1, 2, 3, 1]):
            network = model(graph, seed, kind, constraint)
            values = rollout(graph, network, 0.02)
            name = "{}-{}-seed-{}{}".format(
                kind, constraint, seed, "-repeat" if index == 3 else ""
            )
            np.savez_compressed(
                str(OUT / (name + ".npz")),
                state=values,
                times_s=np.arange(101) * 0.00625,
                names=np.array(names),
            )
            digest = hashlib.sha256(values.tobytes()).hexdigest()
            if index == 0:
                baseline = digest
            if index == 3:
                assert digest == baseline
            cases.append(
                {"name": name, "shape": list(values.shape), "array_sha256": digest}
            )
    for name, stimulus, zero in [("no-input", 0, False), ("zero-synapses", 0.02, True)]:
        values = rollout(
            graph, model(graph, 1, "conductance", "weight"), stimulus, zero
        )
        np.savez_compressed(
            str(OUT / (name + ".npz")),
            state=values,
            times_s=np.arange(101) * 0.00625,
            names=np.array(names),
        )
        cases.append(
            {
                "name": name,
                "shape": list(values.shape),
                "array_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
            }
        )
    summary = {
        "status": "passed",
        "cases": cases,
        "repeat_seed_equal": True,
        "nodes": graph.N,
        "scope": "Untrained native dynamics with actual C.elegans connectivity and explicit adapter stimulus/initialization; no fitted voltage, spikes, body or nociception",
        "dt_s": 0.00625,
        "time_origin": "zero initial state included before first update",
        "state_units": "native latent values, not calibrated mV",
        "weights": "random initialization; no supplied trained checkpoint",
        "recordings": "measured calcium fluorescence is exported separately, not treated as voltage",
    }
    save("dynamics.json", summary)
    summary["native_vae_pipeline"] = vae_pipeline()
    save("functional.json", summary)
    subprocess.run(
        [sys.executable, "/work/probes/wormvae_plot.py"], check=True, timeout=120
    )


def vae_pipeline():
    import torch.nn.functional as F
    from model import (
        Worm_Inference_Network,
        Worm_Sensory_Encoder,
        WormVAE,
        data_loader,
        train,
    )

    graph, data = inputs()
    torch.manual_seed(1)
    n, up, window = graph.N, 40, 30
    params = {
        "k1": 11,
        "k2": 21,
        "k3": 21,
        "k4": 41,
        "k5": 41,
        "up1_factor": 4,
        "up2_factor": 10,
    }
    inference = Worm_Inference_Network(
        n,
        2 * n,
        {"conv1": 2 * n, "conv2": 2 * n, "conv3": 2 * n},
        {"conv" + str(i): params["k" + str(i)] for i in range(1, 6)},
        {"upsample1": 4, "upsample2": 10},
        nonlinearity=F.relu,
    )
    encoder = Worm_Sensory_Encoder(3, n)
    # Same architecture and initialization expressions as the author entry point.
    initialization = {
        "neuron_bias": 1e-3 * torch.rand(1, n),
        "neuron_tau": 1e-2 * torch.rand(1, n),
        "calcium_bias": 1e-2 * torch.rand(1, n),
        "voltage_to_calcium_nonlinearity": F.softplus,
    }
    network = WormVAE(
        graph,
        window,
        initialization,
        up,
        torch.empty(n, n).uniform_(-0.01, 0.01),
        encoder,
        inference,
        "cpu",
        data.step / up,
        F.leaky_relu,
        "conductance",
        "weight",
    )
    # One actual worm, preserving the native measured/missing mask. This is a
    # software test of one native minibatch, not a dissertation training result.
    recorded = torch.from_numpy(data.activity_worms[1:2]).float()
    full = graph.make_full_connectome_activity(recorded, data.neuron_names)
    target, missing = data_loader.generate_target_mask(full)
    odors = torch.from_numpy(data.interpolate_odor(data.odor_worms[1:2], up)).float()
    dataset = data_loader.TimeSeriesDataloader(
        params, [odors, target, missing], [window * up, window, window]
    )
    selected = torch.utils.data.Subset(dataset, [0])
    loader = torch.utils.data.DataLoader(selected, batch_size=1, shuffle=False)
    config = {
        "lr": 3e-4,
        "step_size": 50,
        "epochs": 1,
        "gamma": 0.5,
        "grad_clip": 1.0,
        "eps": 1e-8,
        "ckpt_save_freq": 1,
    }
    losses = train(
        loader, network, "conductance", "weight", config, str(OUT / "native-vae-")
    )
    assert all(len(values) == 1 and np.isfinite(values).all() for values in losses)
    checkpoint = OUT / "native-vae-epoch_0.pt"
    state = torch.load(str(checkpoint), map_location="cpu")
    restored = copy.deepcopy(network)
    restored.load_state_dict(state, strict=True)
    assert all(
        torch.equal(value, restored.state_dict()[key])
        for key, value in network.state_dict().items()
    )
    batch = next(iter(loader))
    args = {
        "odor_input": batch[0][:, 0],
        "fluorescence_full_target": batch[1][:, 0],
        "missing_target_mask": batch[2][:, 0],
        "fluorescence_target": batch[3][:, 0],
        "is_Training": False,
    }
    network.eval()
    restored.eval()
    with torch.no_grad():
        a = network(**args)
        b = restored(**args)
    keys = [
        "voltage_latent_mu",
        "prior_voltage_mu",
        "pred_fluorescence_mu",
        "pred_calcium_mu",
        "sensory_input",
    ]
    for key in keys:
        assert torch.isfinite(a[key]).all() and torch.equal(a[key], b[key])
    np.savez_compressed(
        str(OUT / "native-vae-context.npz"), **{key: a[key].numpy() for key in keys}
    )
    result = {
        "status": "passed",
        "native_training_minibatches": 1,
        "worm_zero_based_index": 1,
        "recorded_window_steps": 30,
        "latent_steps": 1200,
        "upsample_factor": 40,
        "losses": losses,
        "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "checkpoint_restore_exact": True,
        "validated_outputs": {key: list(a[key].shape) for key in keys},
        "scope": "Original VAE architecture, loss and optimizer on one actual measured minibatch; no paper accuracy, held-out evaluation or fitted physiological voltage claimed",
        "evaluation_log_variance": "Native deterministic inference sets posterior std=0 and logvar=-inf; not interpreted as finite uncertainty estimate",
    }
    save("vae-pipeline.json", result)
    return result


if __name__ == "__main__":
    {"smoke": smoke, "software": software, "full": full}[sys.argv[1]]()
