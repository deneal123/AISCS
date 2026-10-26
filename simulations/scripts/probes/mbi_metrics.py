"""Validate actual replay units and render only available stimulation recordings."""

import hashlib
import json
import runpy
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

SOURCE = Path("/work/source")
OUT = Path("/work/exports")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify():
    power = runpy.run_path(str(SOURCE / "src/mbi_paper/power_vs_distance.py"))["data"]
    assert power.shape == (8, 4)
    np.testing.assert_array_equal(
        power["distance"], [0, 3.2, 6.4, 9.6, 12.8, 16.1, 19.3, 22.5]
    )
    raw_power = pd.read_csv(SOURCE / "data/power_consumption.csv").to_numpy()
    np.testing.assert_array_equal(power.to_numpy(), raw_power)
    power.to_csv(OUT / "power-measurements.csv", index=False)

    module = runpy.run_path(str(SOURCE / "src/mbi_paper/benchtop_ephys_figure.py"))
    original, replay = module["plot_data_original"], module["plot_data_replay"]
    base = SOURCE / "data/202401161300-Benchtop"
    independently_original = (
        pd.read_csv(base / "murdoc_nform_20180725_original.csv") * 0.25
    )
    independently_original -= independently_original.mean()
    t = np.arange(len(independently_original)) / 30000
    independently_original = independently_original.loc[(t > 0) & (t < 0.5)]
    np.testing.assert_array_equal(
        original.to_numpy(), independently_original.to_numpy()
    )
    independently_replay = (
        pd.read_csv(base / "murdoc_nform_20180725_replayed.csv") * 0.195
    )
    t = np.arange(len(independently_replay)) / 36931.8
    offset = 1.7192 - 0.00233
    independently_replay = independently_replay.loc[(t > offset) & (t < offset + 0.5)]
    np.testing.assert_array_equal(replay.to_numpy(), independently_replay.to_numpy())
    series = []
    for label, frame in [("original", original), ("replay", replay)]:
        assert frame.index.is_monotonic_increasing and len(frame) > 0
        assert np.isfinite(frame.to_numpy()).all()
        series.append(
            pd.DataFrame(
                {
                    "stream": label,
                    "time_s": frame.index.to_numpy(),
                    "amplitude_uv": frame.iloc[:, 0].to_numpy(),
                }
            )
        )
    pd.concat(series, ignore_index=True).to_csv(
        OUT / "lfp-replay-series.csv", index=False
    )
    plt.close("all")

    directory = SOURCE / "data/202401261300-Benchtop"
    files = sorted(directory.glob("*.csv"))
    assert len(files) == 9
    fig, axes = plt.subplots(3, 3, figsize=(15, 10), layout="constrained")
    traces = []
    for path, ax in zip(files, axes.flat, strict=True):
        frame = pd.read_csv(path, comment="#")
        values = frame.to_numpy(dtype=float)
        assert len(frame) > 0 and np.isfinite(values).all()
        assert np.all(np.diff(values[:, 0]) > 0)
        for column in range(1, values.shape[1]):
            ax.plot(
                values[:, 0] * 1000,
                values[:, column],
                lw=0.6,
                label=str(frame.columns[column]),
            )
        ax.set(
            title=path.stem.replace("_", " "),
            xlabel="Recorded time (ms)",
            ylabel="Recorded voltage (V)",
        )
        ax.tick_params(labelsize=8)
        ax.title.set_fontsize(9)
        ax.spines[["top", "right"]].set_visible(False)
        if values.shape[1] > 2:
            ax.legend(fontsize=8)
        traces.append(
            {
                "file": path.name,
                "rows": len(frame),
                "columns": frame.columns.tolist(),
                "sha256": sha(path),
                "time_s": [float(values[0, 0]), float(values[-1, 0])],
                "finite": True,
            }
        )
    fig.suptitle(
        "Available author oscilloscope recordings — partial inventory, not reconstructed Fig. 5\nAmplitude-sweep 128-step recording is absent; no substitute trace",
        fontsize=13,
    )
    for ext in ["png", "svg"]:
        fig.savefig(OUT / ("available-stimulation-recordings." + ext), dpi=170)
    plt.close(fig)
    info = {
        "status": "passed",
        "scope": "recorded data and exact author replay conversions; not forward simulation or physiological validation",
        "power_rows": len(power),
        "power_header_includes_hash_character": True,
        "lfp_samples": {"original": len(original), "replay": len(replay)},
        "lfp_units": "microvolts before author's +100 uV display offset",
        "original_sample_rate_hz": 30000,
        "replay_sample_rate_hz": 36931.8,
        "adc_to_uv": {"original": 0.25, "replay": 0.195},
        "stimulation_files": traces,
        "unavailable_input": "amp_sweep_128steps_200usec.csv",
        "seed_applicability": "deterministic processing of fixed recordings; seeds are not new biological repetitions",
    }
    (OUT / "measurement-check.json").write_text(json.dumps(info, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": info["status"],
                "power_rows": len(power),
                "stimulation_files": len(traces),
                "lfp_samples": info["lfp_samples"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    verify()
