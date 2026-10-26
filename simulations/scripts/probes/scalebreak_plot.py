"""Visualize the actual retinal arrays and recorded central model responses."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT = Path("/work/exports")
data = json.loads((OUT / "functional.json").read_text())
run = OUT / "run-0-seed-1"
stim = np.load(run / "stimuli/stimuli.npy", mmap_mode="r")
meta = pd.read_csv(run / "stimuli/metadata.csv")
coords = pd.read_csv(run / "stimuli/hex_coordinates.csv")
responses = np.load(run / "responses/flyvis_central_cell_responses.npy", mmap_mode="r")
cells = pd.read_csv(run / "responses/cell_metadata.csv")
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "svg.fonttype": "none",
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)
examples = [
    ("moving_edge", "edge"),
    ("moving_bar", "bar"),
    ("looming_disk", "disk"),
    ("small_translating_target", "target"),
    ("static_shape", "disk"),
    ("static_shape", "square"),
    ("static_shape", "triangle"),
]
fig, axes = plt.subplots(2, 7, figsize=(15, 5), layout="constrained")
for column, (family, shape) in enumerate(examples):
    selected = meta[
        (meta.feature_family == family)
        & (meta["shape"] == shape)
        & (meta.scale == 6)
        & (meta.angle == 0)
        & (meta["repeat"] == 0)
    ].iloc[0]
    for row, frame in enumerate((4, 7)):
        ax = axes[row, column]
        ax.scatter(
            coords.x,
            coords.y,
            c=stim[int(selected["sample"]), frame, 0],
            marker="h",
            s=21,
            cmap="gray",
            vmin=0,
            vmax=1,
            linewidths=0,
        )
        ax.set(aspect="equal", xticks=[], yticks=[])
        for spine in ax.spines.values():
            spine.set_visible(False)
        if row == 0:
            ax.set_title(
                family.replace("_", "\n")
                if family != "static_shape"
                else "static\n" + shape
            )
        if column == 0:
            ax.set_ylabel(
                f"t = {frame * data['units']['dt_seconds'] - 0.02:.3f} s", fontsize=11
            )
fig.suptitle(
    "SIM-019 | Native synthetic retinal inputs (721 samples; model 000)", fontsize=14
)
fig.supxlabel(
    "Selected frames, seed 1; scale 6 is a retinal geometry parameter, not physical distance",
    fontsize=11,
)
for extension in ("png", "svg"):
    fig.savefig(OUT / ("native-retinal-inputs." + extension), dpi=160)
plt.close(fig)

selected = meta[
    (meta.feature_family == "moving_bar")
    & (meta.scale == 6)
    & (meta.angle == 0)
    & (meta["repeat"] == 0)
].iloc[0]
values = np.asarray(responses[int(selected["sample"])])
delta = values - values[: round(0.02 / data["units"]["dt_seconds"])].mean(
    axis=0, keepdims=True
)
t = np.arange(12) * data["units"]["dt_seconds"] - 0.02
fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
scale = max(float(np.abs(delta).max()), 1e-8)
picture = axes[0].imshow(
    delta.T,
    aspect="auto",
    origin="lower",
    cmap="RdBu_r",
    vmin=-scale,
    vmax=scale,
    extent=[t[0], t[-1], -0.5, len(cells) - 0.5],
)
ticks = list(range(0, len(cells), 5))
axes[0].set(
    yticks=ticks,
    yticklabels=cells.cell_type.iloc[ticks],
    xlabel="Time relative to active input (s)",
    ylabel="Central cell type",
    title="Recorded response to the moving bar (one trial)",
)
fig.colorbar(
    picture, ax=axes[0], label="Baseline-subtracted model activity", shrink=0.85
)
idx = np.flatnonzero(cells.cell_type.str.startswith(("T4", "T5")))
for variant in data["interventions"]:
    name = variant["variant"]
    activity = np.load(OUT / ("perturb-" + name + ".npy"))[0]
    if variant["finite"]:
        axes[1].plot(
            t,
            activity[:, idx].mean(axis=1),
            label=name.replace("_", " "),
            linewidth=1.5,
        )
    else:
        axes[1].text(
            0.02,
            0.98,
            name.replace("_", " ") + ": nonfinite; omitted from plot",
            transform=axes[1].transAxes,
            va="top",
            fontsize=8,
        )
axes[1].set(
    xlabel="Time relative to active input (s)",
    ylabel="Mean T4/T5 model activity",
    title="Acute interventions on the first moving-edge trial",
)
axes[1].legend(fontsize=8)
fig.suptitle(
    "SIM-019 | Pretrained model outputs; no biological or cross-species validation",
    fontsize=12,
)
for extension in ("png", "svg"):
    fig.savefig(OUT / ("recorded-model-responses." + extension), dpi=160)
plt.close(fig)
