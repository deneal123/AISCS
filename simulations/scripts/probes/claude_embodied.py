"""Observe unchanged author headless CLI; instrumentation does not alter dynamics."""

import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, "/work/source")
import fly_embodied as author

OUT = Path("/work/export")
OUT.mkdir(exist_ok=True)
np.random.seed(1)
torch.manual_seed(1)
states, neural, instances = [], [], []
original_body_step = author.HybridTurningController.step
original_brain_step = author.BrainEngine.step
fresh = "--fresh" in sys.argv
if fresh:
    original_brain_init = author.BrainEngine.__init__

    def brain_init(self, device="cuda", plastic_path=None):
        target = OUT / "author-fresh-weights.pt"
        if target.exists():
            raise ValueError("Fresh embodied scenario must not restore previous output")
        original_brain_init(self, device=device, plastic_path=str(target))

    author.BrainEngine.__init__ = brain_init


def body_step(self, action):
    result = original_body_step(self, action)
    observation = result[0]
    states.append(np.asarray(observation["fly"]).copy())
    if not instances:
        instances.append(self)
    return result


def brain_step(self):
    result = original_brain_step(self)
    neural.append(int(result.sum()))
    return result


author.HybridTurningController.step = body_step
author.BrainEngine.step = brain_step
sys.argv = [
    "fly_embodied.py",
    "--no-viewer",
    "--no-auto",
    "--stimulus",
    "sugar",
    "--duration",
    "0.1",
]
author.main()
assert states and neural
values = np.asarray(states)
assert np.isfinite(values).all()
np.savez(OUT / "embodied-states.npz", body=values, brain_spikes=neural)
receipt = {
    "status": "passed",
    "scope": "instrumented author headless CLI, 0.1 second body time",
    "initialization": "author fresh-weights condition"
    if fresh
    else "author default checkpoint",
    "pretrained_weights_reproduced": not fresh,
    "body_steps": len(states),
    "brain_steps": len(neural),
    "body_dt_seconds": 0.0001,
    "brain_dt_ms": 0.1,
    "body_shape": list(values.shape),
    "finite": True,
    "body_seed": 0,
    "numpy_and_torch_seed": 1,
    "time_scale_note": "Author BRAIN_RATIO=100: one 0.1 ms brain step per 10 ms body time; clocks differ by 100.",
    "biological_validation": False,
    "behavior_reproduction": False,
}
try:
    import imageio.v3 as iio

    sim = instances[0]
    image = sim.physics.render(height=720, width=960, camera_id=0)
    iio.imwrite(OUT / "embodied-snapshot.png", image)
    receipt["snapshot"] = "embodied-snapshot.png"
except (OSError, RuntimeError, ValueError) as exc:
    receipt["snapshot_error"] = str(exc)
(OUT / "embodied.json").write_text(
    json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(receipt, indent=2))
