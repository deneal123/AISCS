"""Display recorded full-model states and events, without implying fitted accuracy."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

out = Path("/work/exports")
summary = json.loads((out / "functional.json").read_text())
fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
baseline = np.load(out / "seed-1.npz", allow_pickle=False)
events = baseline["events"]
axes[0, 0].scatter(
    (events[:, 0] + 1) * 0.2, events[:, 1], s=1, alpha=0.6, rasterized=True
)
axes[0, 0].set(
    xlabel="Native model time, ms",
    ylabel="Model index (ID map exported)",
    title="Original v630 model: simulated spike events",
)
for item in summary["cases"]:
    if item["name"].endswith("repeat"):
        continue
    data = np.load(out / item["file"], allow_pickle=False)
    axes[0, 1].plot(
        data["times_ms"], data["voltage_mV"].mean(axis=1), label=item["name"]
    )
    count = np.bincount(data["events"][:, 0], minlength=50)
    axes[1, 0].plot(data["times_ms"], count, label=item["name"])
axes[0, 1].set(
    xlabel="Native model time, ms",
    ylabel="Mean nominal model voltage, mV",
    title="Untrained parameters; native Poisson-drive controls",
)
axes[0, 1].legend(fontsize=9)
axes[1, 0].set(
    xlabel="Native model time, ms",
    ylabel="Events per update",
    title="Seeds 1/2/3 and no-input control",
)
axes[1, 0].legend(fontsize=9)
if len(events):
    selected = np.unique(events[:, 1])[:5]
else:
    selected = np.arange(5)
for index in selected:
    axes[1, 1].plot(
        baseline["times_ms"],
        baseline["voltage_mV"][:, index],
        label=str(baseline["ids"][index]),
    )
axes[1, 1].set(
    xlabel="Native model time, ms",
    ylabel="Nominal model voltage, mV",
    title="Example states by exact registered neuron ID",
)
axes[1, 1].legend(fontsize=8)
for ext in ["png", "svg"]:
    fig.savefig(out / ("full-v630-firing-model." + ext), dpi=150)
plt.close(fig)
