"""Plot measured OpticLobe connectivity exports; never fabricate neural activity."""

import csv
import hashlib
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    run = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from inventory import save
    from simctl import checked_work

    checked_work(run)
    folder = run / "exports/optic-lobe"
    csv_path = folder / "intrinsic-connectivity.csv"
    result_path = folder / "full-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    with csv_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    names = rows[0][1:]
    values = np.asarray([row[1:] for row in rows[1:]], dtype=np.int64)
    assert names == [row[0] for row in rows[1:]]
    assert values.shape == (230, 230) and np.isfinite(values).all()
    assert (values >= 0).all()
    fig, axes = plt.subplots(
        1, 2, figsize=(15, 7.5), gridspec_kw={"width_ratios": [1.2, 1]}
    )
    image = axes[0].imshow(
        np.log10(1 + values), cmap="viridis", interpolation="nearest"
    )
    ticks = np.arange(0, len(names), 20)
    axes[0].set_xticks(ticks, [names[i] for i in ticks], rotation=60, ha="right")
    axes[0].set_yticks(ticks, [names[i] for i in ticks])
    axes[0].set(
        xlabel="Postsynaptic type",
        ylabel="Presynaptic type",
        title="230 intrinsic optic-lobe types",
    )
    fig.colorbar(image, ax=axes[0], shrink=0.7, label="log10(1 + synapse count)")
    targets = result["example_top_targets"][::-1]
    axes[1].barh(
        [x["type"] for x in targets], [x["synapses"] for x in targets], color="#315c91"
    )
    axes[1].set(
        xlabel="Synapses to visual target types",
        title="One Tm1 cell: strongest output partners",
    )
    axes[1].spines[["top", "right"]].set_visible(False)
    fig.suptitle("OpticLobe.jl / FlyWire v783 / Princeton synapses", fontsize=16)
    fig.text(
        0.5,
        0.025,
        "Static anatomical connectivity after upstream filtering; not a neuronal simulation or ECAP",
        ha="center",
    )
    fig.tight_layout(rect=(0, 0.13, 1, 0.94))
    outputs = []
    for ext in ["png", "svg"]:
        target = folder / ("connectivity-analysis." + ext)
        fig.savefig(target, dpi=180)
        outputs.append(
            {
                "file": target.name,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    plt.close(fig)
    save(
        folder / "plot-provenance.json",
        {
            "command": sys.argv,
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "matplotlib": matplotlib.__version__,
            "numpy": np.__version__,
            "inputs": [
                {"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in [csv_path, result_path]
            ],
            "outputs": outputs,
            "transform": "log10(1 + count), no resampling or network dynamics",
        },
    )


if __name__ == "__main__":
    main()
