"""Short inference of the author's Figure 1 teacher; not a whole-brain model."""

import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np
import torch

sys.dont_write_bytecode = True
sys.path.insert(0, "/work/source")
import fun_lib as fl

torch.set_num_threads(4)
torch.use_deterministic_algorithms(True)
weights = Path("/work/source/Data/Figure1/teacherRNN_cycling.npz")
with np.load(weights, allow_pickle=False) as data:
    J, gt, bt, wI, wout, x0, mask, signs = [data[f"arr_{i}"].copy() for i in range(8)]
n = wI.shape[1]
assert n <= 512
outdir = Path("/work/exports/connconstr-author-teacher")
outdir.mkdir(parents=True, exist_ok=True)
outputs, results = [], []
for attempt, seed in enumerate([1, 2, 3, 1]):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    inputs, _, _ = fl.create_input(np.arange(0, 20, 0.05), 2)
    tensors = [torch.from_numpy(x).float() for x in [wI, np.eye(n), J, mask, signs, bt[:, None], gt[:, None]]]
    net = fl.RNNgain(wI.shape[0], n, n, *tensors, h0_init=torch.from_numpy(x0).float(),
                     train_b=False, train_g=False, train_conn=False, train_wout=False,
                     train_h0=False, noise_std=0.002, alpha=0.05, linear=False)
    with torch.no_grad():
        activity = net(torch.from_numpy(inputs).float()).numpy()
    readout = activity.dot(wout[:, None])
    assert activity.shape == (2, 400, n) and np.isfinite(activity).all() and np.isfinite(readout).all()
    outputs.append(activity)
    artifact = outdir / f"seed{seed}-attempt{attempt}.npz"
    np.savez(artifact, inputs=inputs, activity=activity, readout=readout)
    results.append({"seed": seed, "shape": list(activity.shape), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()})
np.testing.assert_array_equal(outputs[0], outputs[3])
(outdir / "result.json").write_text(json.dumps({
    "status": "passed", "scope": "author Figure1 synthetic teacher; not Drosophila whole brain or paper reproduction",
    "neurons": n, "weights_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
    "seeds": results, "repeat_seed_equal": True, "alpha": 0.05,
    "noise_std": 0.002, "units": "model units from nn_fig1_plots.py",
}, indent=2), encoding="utf-8")
print("PASS: author teacher weights, seeded inference and finite neural activity/readout")
