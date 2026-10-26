"""Render only measured Pugliese rates and native neuron annotations."""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

out = Path("/work/exports")
table = pd.read_csv(
    Path.cwd()
    / "data/manc t1 connectome data/wTable_20250813_DNtoMN_unsorted_withModules.csv",
    index_col=0,
)
baseline = np.load(out / "baseline-seed-1.npz")
rates, times = baseline["rates"], baseline["times"]
motor = np.flatnonzero(table["class"].eq("motor neuron"))
ranked = motor[np.argsort(rates[motor].std(axis=1))[-12:]]
plt.rcParams.update(
    {"font.size": 12, "axes.spines.top": False, "axes.spines.right": False}
)
fig, axes = plt.subplots(2, 1, figsize=(14, 9), constrained_layout=True)
image = axes[0].imshow(
    rates,
    aspect="auto",
    origin="lower",
    extent=[times[0], times[-1], 0, len(rates)],
    cmap="magma",
    interpolation="nearest",
)
axes[0].set(
    xlabel="Model time, s",
    ylabel="Neuron index in registered MANC table",
    title="Recorded activity of the 4,604-neuron rate model",
)
fig.colorbar(image, ax=axes[0], label="Native model rate (source label: Hz)")
for index in ranked[-6:]:
    axes[1].plot(
        times, rates[index], linewidth=1, label=f"bodyId {table.iloc[index].bodyId}"
    )
axes[1].set(
    xlabel="Model time, s",
    ylabel="Model rate",
    title="Motor neurons selected by recorded temporal variation",
)
axes[1].legend(ncol=3, fontsize=9)
fig.savefig(out / "manc-rate-recordings.png", dpi=160)
fig.savefig(out / "manc-rate-recordings.svg")
plt.close(fig)
sys.path.insert(0, str(Path.cwd()))
from src.utils.plot_utils import plot_R_traces_stacked_by_module

fig, ax = plt.subplots(figsize=(12, 5))
plot_R_traces_stacked_by_module(
    rates[:, :751], table.loc[ranked[-6:]], ax=ax, figsize=(12, 5)
)
ax.set_title("Native motor-module plot: first 0.75 model seconds")
ax.set_xlabel("Sample index (native renderer hides ticks; saved interval 1 ms)")
fig.savefig(out / "native-motor-modules.png", dpi=160, bbox_inches="tight")
fig.savefig(out / "native-motor-modules.svg", bbox_inches="tight")
plt.close(fig)
pd.DataFrame(
    {
        "time_s": times,
        **{
            f"model_rate_bodyId_{table.iloc[index].bodyId}": rates[index]
            for index in ranked[-6:]
        },
    }
).to_csv(out / "selected-motor-rates.csv", index=False)
fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
for name, label in [
    ("baseline-seed-1", "seed 1"),
    ("baseline-seed-2", "seed 2"),
    ("baseline-seed-3", "seed 3"),
]:
    data = np.load(out / (name + ".npz"))
    axes[0, 0].plot(data["times"], data["rates"][motor].mean(axis=0), label=label)
axes[0, 0].set(title="Three parameter seeds", ylabel="Mean motor-neuron model rate")
axes[0, 0].legend()
for name, label in [
    ("baseline-seed-1", "baseline"),
    ("no-input", "input = 0"),
    ("stim-neuron-disconnected", "stimulated neuron disconnected"),
    ("tau-15ms", "tau mean = 15 ms"),
]:
    data = np.load(out / (name + ".npz"))
    axes[0, 1].plot(data["times"], data["rates"][motor].mean(axis=0), label=label)
axes[0, 1].set(title="Functional controls", ylabel="Mean motor-neuron model rate")
axes[0, 1].legend(fontsize=9)
for name, label in [
    ("baseline-seed-1", "tutorial tolerances"),
    ("paper-tolerance", "paper tolerances"),
]:
    data = np.load(out / (name + ".npz"))
    axes[1, 0].plot(data["times"], data["rates"][motor].mean(axis=0), label=label)
axes[1, 0].set(
    title="Numerical tolerance comparison", ylabel="Mean motor-neuron model rate"
)
axes[1, 0].legend(fontsize=9)
data = np.load(out / "stim-neuron-disconnected.npz")
axes[1, 1].plot(data["times"], data["rates"][31], label="directly forced neuron #31")
axes[1, 1].plot(
    data["times"], data["rates"][motor].mean(axis=0), label="motor-neuron mean"
)
axes[1, 1].set(
    title="Connectivity removal does not clamp forced input", ylabel="Model rate"
)
axes[1, 1].legend(fontsize=9)
for ax in axes.flat:
    ax.set_xlabel("Model time, s")
fig.savefig(out / "manc-rate-controls.png", dpi=160)
fig.savefig(out / "manc-rate-controls.svg")
plt.close(fig)
(out / "visuals.json").write_text(
    json.dumps(
        {
            "scope": "Observer plots of exported native rates; not experimental fly data",
            "files": [
                "manc-rate-recordings.png",
                "manc-rate-recordings.svg",
                "manc-rate-controls.png",
                "manc-rate-controls.svg",
                "native-motor-modules.png",
                "native-motor-modules.svg",
            ],
        },
        indent=2,
    )
    + "\n"
)
