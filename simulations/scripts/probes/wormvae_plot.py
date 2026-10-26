"""Display actual worm fluorescence and separately labelled untrained model states."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

out = Path("/work/exports")
data = np.load(str(out / "recorded-inputs.npz"), allow_pickle=False)
fig, axes = plt.subplots(2, 1, figsize=(13, 8), constrained_layout=True)
for i in range(6):
    axes[0].plot(
        np.arange(800) * float(data["step_s"]),
        data["fluorescence"][0, i],
        label=str(data["names"][i]),
    )
axes[0].set(
    title="Native loader: measured worm-0 calcium traces (baseline +2)",
    xlabel="Time after native 40-s crop, s",
    ylabel="Native fluorescence value",
)
axes[0].legend(ncol=6)
for i in range(3):
    axes[1].plot(
        np.arange(800) * float(data["step_s"]),
        data["odors"][0, i],
        label=["butanone", "pentanedione", "NaCl"][i],
    )
axes[1].set(xlabel="Time after native crop, s", ylabel="Native stimulus encoding")
axes[1].legend()
for ext in ["png", "svg"]:
    fig.savefig(str(out / ("recorded-calcium-inputs." + ext)), dpi=150)
plt.close(fig)
fig, axes = plt.subplots(2, 1, figsize=(13, 8), constrained_layout=True)
for kind, constraint in [
    ("conductance", "weight"),
    ("conductance", "sparsity"),
    ("current", "sparsity"),
]:
    row = np.load(str(out / (kind + "-" + constraint + "-seed-1.npz")))
    axes[0].plot(
        row["times_s"], row["state"].mean(axis=1), label=kind + ":" + constraint
    )
axes[0].set(
    title="Untrained original dynamics: mean latent state on real worm graph",
    xlabel="Native model time, s",
    ylabel="Mean latent value",
)
axes[0].legend()
for name in ["conductance-weight-seed-1", "no-input", "zero-synapses"]:
    row = np.load(str(out / (name + ".npz")))
    axes[1].plot(row["times_s"], row["state"].mean(axis=1), label=name)
axes[1].set(
    xlabel="Native model time, s",
    ylabel="Mean latent value",
    title="Adapter controls, not fitted or biological responses",
)
axes[1].legend()
for ext in ["png", "svg"]:
    fig.savefig(str(out / ("untrained-worm-dynamics." + ext)), dpi=150)
plt.close(fig)
