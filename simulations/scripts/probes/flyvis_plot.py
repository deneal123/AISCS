"""Recorded optic-lobe activities and native visual stimuli, without model cartoons."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

out = Path("/work/exports")
nodes = np.load(out / "nodes.npz", allow_pickle=False)
types, u, v = nodes["cell_type"], nodes["u"], nodes["v"]
chosen = []
for name in ["L1", "L2", "Mi1", "Tm1", "Tm3", "T4a", "T4b", "T5a"]:
    indices = np.flatnonzero((types == name) & (u == 0) & (v == 0))
    if len(indices):
        chosen.append((name, indices[0]))
assert chosen
plt.rcParams.update(
    {"font.size": 11, "axes.spines.top": False, "axes.spines.right": False}
)
fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
for ax, case in zip(
    axes.flat,
    [
        "native-flash-0",
        "native-flash-1",
        "native-moving-edge-0",
        "native-moving-edge-1",
    ],
    strict=True,
):
    data = np.load(out / (case + ".npz"))
    for label, index in chosen:
        ax.plot(
            data["times_s"], data["activity"][0, :, index], label=label, linewidth=1.2
        )
    ax.set(title=case, xlabel="Native model time, s", ylabel="Model activity")
    ax.legend(ncol=4, fontsize=9)
fig.savefig(out / "native-visual-responses.png", dpi=150)
fig.savefig(out / "native-visual-responses.svg")
plt.close(fig)
fig, axes = plt.subplots(2, 1, figsize=(14, 8), constrained_layout=True)
for name in [
    "native-moving-edge-0",
    "zero-synaptic-strength",
    "T4a-state-clamp",
    "restored-moving-edge",
]:
    data = np.load(out / (name + ".npz"))
    index = next(index for label, index in chosen if label == "T4a")
    axes[0].plot(data["times_s"], data["activity"][0, :, index], label=name)
axes[0].set(
    xlabel="Native model time, s",
    ylabel="Central T4a model activity",
    title="Recorded native-hook and synaptic-strength controls",
)
axes[0].legend(fontsize=9)
for seed in [1, 2, 3]:
    data = np.load(out / f"noise-seed-{seed}.npz")
    axes[1].plot(
        data["times_s"],
        data["activity"].mean(axis=(0, 2)),
        label=f"external stimulus seed {seed}",
    )
axes[1].set(
    xlabel="Native model time, s",
    ylabel="Mean model activity",
    title="Fixed pretrained parameters; three different input realizations",
)
axes[1].legend(fontsize=9)
fig.savefig(out / "optic-lobe-controls.png", dpi=150)
fig.savefig(out / "optic-lobe-controls.svg")
plt.close(fig)
fig, ax = plt.subplots(figsize=(14, 5), constrained_layout=True)
data = np.load(out / "native-moving-edge-0.npz")
image = ax.imshow(
    data["input"][0, :, 0].T,
    aspect="auto",
    origin="lower",
    cmap="Greys_r",
    extent=[0, data["times_s"][-1], 0, 721],
    vmin=0,
    vmax=1,
)
ax.set(
    xlabel="Native model time, s",
    ylabel="Retinal hexal index",
    title="Actual native moving-edge input passed to the model",
)
fig.colorbar(image, ax=ax, label="Normalized luminance")
fig.savefig(out / "native-retinal-input.png", dpi=150)
fig.savefig(out / "native-retinal-input.svg")
plt.close(fig)
(out / "visuals.json").write_text(
    json.dumps(
        {
            "scope": "plots of newly recorded responses from pinned Flyvis and official checkpoint; not physiological recordings",
            "central_cell_types": [name for name, _ in chosen],
        },
        indent=2,
    )
    + "\n"
)
