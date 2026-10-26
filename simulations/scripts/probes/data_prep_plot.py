"""Plots from actual registered matrices and reconstructed notebook outputs."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import sparse

out = Path("/work/exports")
counts = sparse.load_npz(out / "native-rebuilt-ad-counts.npz").tocsc()
inprop = sparse.load_npz(out / "native-rebuilt-ad-inprop.npz").tocsc()
fig, axes = plt.subplots(2, 2, figsize=(13, 10), constrained_layout=True)
axes[0, 0].spy(counts, markersize=0.2, rasterized=True)
axes[0, 0].set(
    title="Rebuilt larval AD connectivity; native recorded node order",
    xlabel="Postsynaptic index",
    ylabel="Presynaptic index",
)
totals = np.asarray(counts.sum(axis=0)).reshape(-1)
axes[0, 1].hist(totals, bins=50)
axes[0, 1].set(
    title="Actual recipient input totals",
    xlabel="Synapse count",
    ylabel="Number of nodes",
)
axes[1, 0].hist(inprop.data, bins=np.logspace(-4, 0, 45))
axes[1, 0].set(
    xscale="log",
    yscale="log",
    title="Recomputed recipient-normalized weights",
    xlabel="Input proportion",
    ylabel="Number of nonzero connections",
)
sums = np.asarray(inprop.sum(axis=0)).reshape(-1)
axes[1, 1].plot(np.arange(len(sums)), sums, ".", markersize=2)
axes[1, 1].set(
    title="Normalization check (zero-input nodes retained)",
    xlabel="Postsynaptic index",
    ylabel="Column sum",
)
for extension in ["png", "svg"]:
    fig.savefig(out / ("larval-preparation-checks." + extension), dpi=150)
plt.close(fig)
