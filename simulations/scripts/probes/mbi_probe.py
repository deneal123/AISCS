"""Separate MBI utility fixtures, primary-recording QC and author figure runs."""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)
SOURCE = Path("/work/source")
SCRIPTS = [
    "power_vs_distance",
    "benchtop_ephys_figure",
    "benchtop_stim_figure",
    "plot_tens_triggered_ephys_per_hd64_routing",
    "plot_tens_triggered_emg_publication",
    "plot_triggered_emg_publication",
    "calculate_spectrum_benchtop",
]


def save(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2) + "\n")
    print(name, json.dumps(data)[:1200], flush=True)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def software():
    from mbi_paper.utils import getThresholdCrossings

    signal = pd.Series([0.0, 2, 0, 3, 0, -4, 0])
    cases = []
    for kind, absolute, expected in [
        ("rising", False, [1, 3]),
        ("falling", False, [2, 4]),
        ("both", False, [1, 2, 3, 4]),
        ("rising", True, [1, 3, 5]),
    ]:
        idx, mask = getThresholdCrossings(
            signal, thresh=1, edgeType=kind, absVal=absolute
        )
        assert idx.tolist() == expected
        assert np.flatnonzero(mask).tolist() == expected
        cases.append({"edge": kind, "absolute": absolute, "indices": expected})
    for strongest, expected in [(True, [3]), (False, [1])]:
        idx, _ = getThresholdCrossings(
            signal.iloc[:5],
            thresh=1,
            iti=0.3,
            fs=10,
            itiWiggle=0,
            keep_max=strongest,
        )
        assert idx.tolist() == expected
        cases.append({"strongest": strongest, "indices": expected})
    for empty in [pd.Series([], dtype=float), pd.Series(np.zeros(5))]:
        idx, mask = getThresholdCrossings(empty, thresh=1)
        assert len(idx) == 0 and not np.any(mask)
    save(
        "software.json",
        {
            "passed": True,
            "scope": "own artificial threshold fixture, not biological validation",
            "cases": cases,
        },
    )


def data():
    ledger = json.loads(Path("/work/mbi-inputs.json").read_text())
    results = []
    for item in ledger["files"]:
        path = SOURCE / "data" / item["path"]
        assert path.stat().st_size == item["bytes"] and digest(path) == item["sha256"]
        record = {
            "path": item["path"],
            "sha256": item["sha256"],
            "bytes": item["bytes"],
        }
        if path.suffix == ".parquet":
            f = pq.ParquetFile(path)
            record.update(
                rows=f.metadata.num_rows,
                columns=f.schema_arrow.names,
                row_groups=f.num_row_groups,
                uncompressed_bytes=sum(
                    f.metadata.row_group(i).total_byte_size
                    for i in range(f.num_row_groups)
                ),
                pandas_metadata=f.schema_arrow.metadata.get(b"pandas", b"{}").decode(),
            )
        elif path.suffix == ".csv":
            # Only the WaveForms files use comments above their real CSV header.
            # power_consumption.csv has a real header starting with '# Acrylic'.
            waveform = path.parent.name == "202401261300-Benchtop"
            frame = pd.read_csv(path, comment="#" if waveform else None)
            numeric = frame.select_dtypes(include="number")
            values = numeric.to_numpy()
            nonfinite = int(np.count_nonzero(~np.isfinite(values)))
            metadata_log = path.name.endswith("_log.csv")
            if not metadata_log:
                assert nonfinite == 0, str(path)
            record.update(
                rows=len(frame),
                columns=frame.columns.tolist(),
                numeric_nonfinite=nonfinite,
                scope="sparse acquisition metadata"
                if metadata_log
                else "recorded numeric table",
            )
        results.append(record)
    missing = SOURCE / "data/202401261300-Benchtop/amp_sweep_128steps_200usec.csv"
    assert not missing.exists()
    save(
        "data.json",
        {
            "verified": len(results),
            "files": results,
            "missing_author_input": str(missing.relative_to(SOURCE)),
        },
    )


def execute(name, suffix=""):
    log = OUT / (name + suffix + ".log")
    started = time.monotonic()
    peak = 0
    with log.open("w") as stream:
        child = subprocess.Popen(
            [sys.executable, "-u", str(SOURCE / "src/mbi_paper" / (name + ".py"))],
            cwd=SOURCE,
            stdout=stream,
            stderr=subprocess.STDOUT,
            env=dict(os.environ, MPLBACKEND="Agg"),
        )
        while child.poll() is None:
            try:
                for line in Path(f"/proc/{child.pid}/status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        peak = max(peak, int(line.split()[1]) * 1024)
            except OSError:
                pass
            if time.monotonic() - started > 1800:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                return {"script": name, "status": "timeout", "peak_rss_bytes": peak}
            time.sleep(0.5)
    return {
        "script": name,
        "returncode": child.returncode,
        "status": "passed" if child.returncode == 0 else "failed",
        "wall_seconds": time.monotonic() - started,
        "peak_rss_bytes": peak,
        "log": log.name,
    }


def full():
    records = []
    for name in SCRIPTS:
        print("Author script", name, flush=True)
        records.append(execute(name))
        save("author-scenarios.json", {"cases": records, "complete": False})
    # A deterministic replay uses the same real power measurements, not new seeds.
    png = SOURCE / "figures/power_vs_distance.png"
    before = digest(png)
    repeat = execute("power_vs_distance", "-repeat")
    assert repeat["status"] == "passed" and before == digest(png)
    from pypdf import PdfReader

    artifacts = []
    for source in sorted((SOURCE / "figures").glob("*")):
        if source.is_file() and source.suffix in {".png", ".pdf"}:
            target = OUT / source.name
            target.write_bytes(source.read_bytes())
            record = {
                "file": target.name,
                "sha256": digest(target),
                "bytes": target.stat().st_size,
            }
            if source.suffix == ".pdf":
                record["pages"] = len(PdfReader(source).pages)
            artifacts.append(record)
    save(
        "author-scenarios.json",
        {
            "cases": records,
            "complete": True,
            "same_primary_input_png_exact": True,
            "repeat": repeat,
            "artifacts": artifacts,
            "scope": "author recorded-data analyses, not ECAP forward simulation",
        },
    )
    from mbi_metrics import verify

    verify()
    if any(r["status"] != "passed" for r in records):
        raise RuntimeError(
            "Partial author reproduction: inspect every retained case log"
        )


if __name__ == "__main__":
    {"software": software, "data": data, "full": full}[sys.argv[1]]()
