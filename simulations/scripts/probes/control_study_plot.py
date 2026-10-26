"""Plot recorded SIM-018 exports without importing FlyVis global plot settings."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def render(out):
    data = json.loads((out / "functional.json").read_text())
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "none",
        }
    )
    colors = {"connectome": "#205d89", "degreepres": "#c46635"}
    markers = {1: "o", 2: "s", 3: "^"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout="constrained")
    for entry in data["trials"][:6]:
        axes[0].plot(
            [0.02, 0.04, 0.06, 0.08],
            entry["mean_by_frame"],
            marker=markers[entry["seed"]],
            color=colors[entry["kind"]],
            linestyle="-" if entry["kind"] == "connectome" else "--",
            linewidth=1.5,
            markersize=4,
            label=f"{entry['kind']}, seed {entry['seed']}",
        )
    axes[0].set(
        xlabel="Time after initial state (s)",
        ylabel="Mean activity (model units)",
        title="Short untrained numerical check",
    )
    axes[0].legend()
    masks = data["masks"]
    axes[1].bar(
        ["seed 1", "seed 2", "seed 3", "seed 1 repeat"],
        [x["endpoint_type_metadata_mismatches"]["target_type"] for x in masks],
        color="#c46635",
    )
    axes[1].set(
        ylabel="Edges with target-type / endpoint mismatch",
        title="Unchanged metadata after rewiring",
    )
    fig.suptitle(
        "SIM-018 | Software checks, not published benchmark reproduction", fontsize=13
    )
    for suffix in ("png", "svg"):
        fig.savefig(out / ("control-study-checks." + suffix), dpi=160)
    plt.close(fig)
    training = json.loads((out / "training-check.json").read_text())
    import csv

    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    for number, entry in enumerate(training["trials"][:6]):
        with (out / f"training-{entry['kind']}-{number // 2}.csv").open(
            newline=""
        ) as stream:
            curve = list(csv.DictReader(stream))
        ax.plot(
            [int(x["iteration"]) for x in curve],
            [float(x["task_loss"]) for x in curve],
            marker=markers[entry["seed"]],
            color=colors[entry["kind"]],
            linestyle="-" if entry["kind"] == "connectome" else "--",
            label=f"{entry['kind']}, seed {entry['seed']}",
        )
    ax.set(
        xlabel="Optimizer step",
        ylabel="Diagnostic MSE",
        xticks=[1, 2],
        title="Two optimizer steps; arbitrary diagnostic target [0, 1]",
    )
    ax.legend(fontsize=9)
    fig.suptitle("SIM-018 | Numerical path check; no generalization claim", fontsize=12)
    for suffix in ("png", "svg"):
        fig.savefig(out / ("control-study-training." + suffix), dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exports", type=Path, default=Path("/work/exports"))
    render(parser.parse_args().exports)
