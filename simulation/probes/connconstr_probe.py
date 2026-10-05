"""Software fixture for real upstream RNN/trainer; not a biological connectome."""

import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np
import torch

sys.dont_write_bytecode = True
sys.path.insert(0, "/work/source")
import fun_lib

torch.set_num_threads(4)
torch.use_deterministic_algorithms(True)
outdir = Path("/work/exports/connconstr-fixture")
outdir.mkdir(parents=True, exist_ok=True)
results = []
outputs = []
for attempt, seed in enumerate([1, 2, 3, 1]):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    n = 8
    inputs = torch.randn(4, 16, 2) * 0.1
    target = inputs[:, :, :1]
    net = fun_lib.RNN(
        2, n, 1, torch.randn(2, n) * 0.1, torch.randn(n, 1) * 0.1,
        torch.randn(n, n) * 0.01, torch.ones(n, n), torch.zeros(n, n),
        torch.zeros(n, 1), torch.ones(n, 1), noise_std=0,
    )
    before = net(inputs).detach().numpy().copy()
    assert before.shape == (4, 16, 1) and np.isfinite(before).all()
    np.testing.assert_array_equal(before, net(inputs).detach().numpy())
    before_params = {k: v.detach().clone() for k, v in net.state_dict().items()}
    losses, _, _ = fun_lib.train(
        net, inputs, target, torch.ones(4, 16, 1), n_epochs=3,
        batch_size=4, cuda=False, save_loss=True, save_params=False, verbose=False,
    )
    after = net(inputs).detach().numpy().copy()
    assert len(losses) == 3 and np.isfinite(losses).all() and np.isfinite(after).all()
    assert any(not torch.equal(v, net.state_dict()[k]) for k, v in before_params.items())
    net.load_state_dict(before_params)
    np.testing.assert_array_equal(before, net(inputs).detach().numpy())
    artifact = outdir / f"seed{seed}-attempt{attempt}.npz"
    np.savez(artifact, inputs=inputs.numpy(), target=target.numpy(), before=before, after=after, losses=losses)
    results.append({"seed": seed, "shape": list(after.shape), "losses": losses, "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()})
    outputs.append(after)
np.testing.assert_array_equal(outputs[0], outputs[3])
(outdir / "result.json").write_text(json.dumps({
    "status": "passed", "scope": "8-neuron software fixture, not author data or a registered connectome",
    "torch": torch.__version__, "seeds": results, "repeat_seed_equal": True,
    "state_restore_equal": True, "units": "abstract model units; no ECAP or physiological time claims",
}, indent=2), encoding="utf-8")
print("PASS: upstream RNN forward/trainer, finite outputs, parameter restore, seeds 1/2/3 and repeat 1")
