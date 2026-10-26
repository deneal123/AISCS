"""Verify/read the sealed bundle; never call this a regeneration of the model."""

import hashlib
import json
import math
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path, PurePosixPath

SOURCE = Path.cwd()
OUT = Path("/work/exports")
OUT.mkdir(exist_ok=True)


def save(name, data):
    (OUT / name).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest(path):
    result = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        digest, name = line.split(None, 1)
        posix = PurePosixPath(name)
        if (
            len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or posix.is_absolute()
            or ".." in posix.parts
            or name in result
        ):
            raise ValueError("Invalid or duplicate bundle manifest record")
        result[name] = digest
    if not result:
        raise ValueError("Empty verification manifest is not complete evidence")
    return result


def finite_json(value):
    if isinstance(value, float):
        assert math.isfinite(value)
        return 1
    if isinstance(value, dict):
        return sum(finite_json(v) for v in value.values())
    if isinstance(value, list):
        return sum(finite_json(v) for v in value)
    return 0


def inspect():
    entries = read_manifest(SOURCE / "MANIFEST.sha256")
    assert len(entries) == 30
    for name, expected in entries.items():
        assert sha(SOURCE / name) == expected, name
    summaries = []
    for path in sorted((SOURCE / "results").rglob("*.json")):
        data = json.loads(path.read_text())
        summaries.append(
            {
                "file": path.relative_to(SOURCE).as_posix(),
                "keys": list(data),
                "finite_floats": finite_json(data),
                "sha256": sha(path),
            }
        )
    assert len(summaries) == 17
    figures = sorted((SOURCE / "figures").glob("*.pdf"))
    assert len(figures) == 6
    assert all(p.read_bytes().startswith(b"%PDF-") for p in figures)
    save(
        "inspection.json",
        {
            "status": "passed",
            "manifest_entries": len(entries),
            "json": summaries,
            "pdf": [
                {"file": p.name, "bytes": p.stat().st_size, "sha256": sha(p)}
                for p in figures
            ],
            "npz_files": len(list(SOURCE.rglob("*.npz"))),
            "numerical_pipeline_files": [],
            "scope": "complete pinned result bundle, not regenerated dynamics",
        },
    )
    print(
        "Read 17 finite JSON result files and six PDF figures; 30 manifest entries verified"
    )


def interval(value):
    if isinstance(value, int):
        return Decimal(value), Decimal(value)
    assert isinstance(value, Decimal)
    half = Decimal(10) ** value.as_tuple().exponent / 2
    return value - half, value + half


def compatible_z(value, mean, sd, reported):
    v0, v1 = interval(value)
    m0, m1 = interval(mean)
    s0, s1 = interval(sd)
    assert s0 > 0
    possible = [(v - m) / s for v in [v0, v1] for m in [m0, m1] for s in [s0, s1]]
    z0, z1 = interval(reported)
    return {
        "compatible_at_reported_precision": max(min(possible), z0)
        <= min(max(possible), z1),
        "z_interval_from_rounded_summaries": [str(min(possible)), str(max(possible))],
        "reported_z": str(reported),
    }


def read(name, decimals=False):
    return json.loads(
        (SOURCE / "results" / name).read_text(),
        **({"parse_float": Decimal} if decimals else {}),
    )


def verifier_fixture():
    base = Path("/work/verifier-fixture")
    base.mkdir(exist_ok=True)
    shutil.copyfile(SOURCE / "verify.py", base / "verify.py")
    payload = base / "payload.txt"
    payload.write_bytes(b"known verification fixture\n")
    (base / "MANIFEST.sha256").write_text(sha(payload) + "  payload.txt\n")
    cases = []
    for name, expected in [
        ("intact", 0),
        ("changed", 1),
        ("missing", 1),
        ("manifest-missing", 1),
    ]:
        if name == "changed":
            payload.write_bytes(b"changed fixture\n")
        if name == "missing":
            payload.unlink()
        if name == "manifest-missing":
            (base / "MANIFEST.sha256").unlink()
        p = subprocess.run(
            [sys.executable, str(base / "verify.py")],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert p.returncode == expected, name
        cases.append(
            {
                "case": name,
                "exit_code": p.returncode,
                "stdout": p.stdout,
                "stderr": p.stderr,
            }
        )
    return cases


def audit():
    first = subprocess.run(
        [sys.executable, "verify.py"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    second = subprocess.run(
        [sys.executable, "verify.py"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert first.returncode == second.returncode == 0
    assert (
        first.stdout == second.stdout
        and "30 OK, 0 mismatched, 0 missing" in first.stdout
    )
    zchecks = []
    for name in [
        "global_operator/netstats_results.json",
        "global_operator/b5_results.json",
    ]:
        data = read(name, decimals=True)
        for key, stats in data["ensemble"].items():
            item = compatible_z(
                stats["connectome"], stats["mean_n1000"], stats["sd_n1000"], stats["z"]
            )
            assert item["compatible_at_reported_precision"], (name, key, item)
            zchecks.append({"file": name, "metric": key, **item})
    c4 = read("confinement/c4_results.json", decimals=True)
    count = c4["connectome"]["n_active"]
    fraction = Decimal(count) / Decimal(2825)
    lo, hi = interval(c4["connectome"]["active_fraction"])
    assert lo <= fraction <= hi
    item = compatible_z(
        c4["connectome"]["active_fraction"],
        c4["ensemble_n1000"]["mean"],
        c4["ensemble_n1000"]["sd"],
        c4["connectome_z"],
    )
    assert item["compatible_at_reported_precision"]
    zchecks.append({"file": "confinement/c4_results.json", **item})
    panel = read("mode_leverage/leverage_results.json")["panel"]
    assert len(panel) == len({(x["set"], x["subspace"], x["m"]) for x in panel}) == 105
    assert (
        len({x["set"] for x in panel}) == 7 and len({x["subspace"] for x in panel}) == 3
    )
    reference = read("confinement/dw_reference_n50.json")
    assert set(reference) == {str(seed) for seed in range(2000, 2050)}
    fwer = read("mode_leverage/mode_fwer_results.json", decimals=True)
    probabilities = []
    for cell in fwer["flagged_cells"]:
        lower, upper = interval(cell["p_adj_105"])
        candidates = [
            k for k in range(1, 1002) if lower <= Decimal(k) / Decimal(1001) <= upper
        ]
        assert candidates
        probabilities.append(
            {
                "set": cell["set"],
                "m": cell["m"],
                "reported": str(cell["p_adj_105"]),
                "compatible_max_statistic_exceedance_numerators": candidates,
            }
        )
    missing = {
        "status": "blocked",
        "reason": "full numerical pipeline and raw 1000-instance ensemble absent at pinned commit",
        "original_graph_files": "full hashes and graph inputs not supplied in this verification bundle",
        "README_npz_claim": "README mentions one npz; tracked tree contains none",
        "not_reproduced": [
            "operator construction",
            "null ensemble generation",
            "drive dynamics",
            "scoring from graph",
            "FWER from raw null ensemble",
            "figure regeneration from analysis pipeline",
        ],
    }
    save("pipeline-availability.json", missing)
    save(
        "audit.json",
        {
            "status": "passed",
            "scope": "sealed-result arithmetic/shape/precision consistency only; no new simulation or regenerated results",
            "repeat_content_equal": True,
            "native_verifier_stdout": first.stdout,
            "verifier_fixture": verifier_fixture(),
            "z_checks": zchecks,
            "active_fraction_count": {
                "n_active": count,
                "core_neurons": 2825,
                "computed_fraction": str(fraction),
            },
            "mode_panel": {"unique_cells": 105, "sets": 7, "subspaces": 3},
            "seed_registry_50": "2000-2049 present in sealed dw_reference_n50; no null generated",
            "fwer_precision_checks": probabilities,
        },
    )
    print(
        "Native verifier repeated exactly; four corruption fixtures and sealed arithmetic checks passed"
    )


if __name__ == "__main__":
    {"inspect": inspect, "audit": audit}[sys.argv[1]]()
