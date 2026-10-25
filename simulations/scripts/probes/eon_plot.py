"""Plot an already verified Eon output; not biological or clinical observations."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

source = Path("/work/source")
output = Path("/work/exports/eon")
receipt = json.loads((output / "full-result.json").read_text())
trial = receipt["trials"][0]
path = Path(trial["path"])
data = pd.read_parquet(path if path.is_absolute() else source / path)
active = sorted(data.neuron_index.unique())
ranks = {value: index for index, value in enumerate(active)}
figure, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, height_ratios=[3, 1])
axes[0].scatter(
    data.time_ms, data.neuron_index.map(ranks), marker="|", s=12, color="#244c74"
)
axes[0].set_ylabel("Active-neuron rank\n(index order, not anatomy)")
axes[0].set_title(
    f"Eon / FlyWire v783: {receipt['neurons']:,} neurons, seed 1, CPU\n"
    f"{len(data):,} model spikes; {len(active)} active neurons over 100 ms",
    loc="left",
)
axes[1].hist(data.time_ms, bins=np.arange(101), color="#244c74", linewidth=0)
axes[1].set_ylabel("Spikes / 1 ms")
axes[1].set_xlabel("Model time (ms)")
axes[1].set_xlim(0, 100)
for axis in axes:
    axis.spines[["top", "right"]].set_visible(False)
figure.text(
    0.1,
    0.015,
    "Simulation output, not measured neural activity or human ECAP.",
    fontsize=9,
)
figure.tight_layout(rect=[0, 0.035, 1, 1])
figure.savefig(output / "spike-raster-seed1.png", dpi=200)
figure.savefig(output / "spike-raster-seed1.pdf")
plt.close(figure)
data[["neuron_index", "flywire_id"]].drop_duplicates().sort_values(
    "neuron_index"
).to_csv(
    output / "active-neuron-ids.csv",
    index=False,
)
print("Saved a model spike raster and count histogram; no anatomical interpretation")
