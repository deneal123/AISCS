"""Restore selected pinned supplemental tables into the SIM-008 work copy."""

import hashlib
import subprocess
from pathlib import Path

FILES = (
    "supplemental_data/dnan_cluster_function_20260509.csv",
    "supplemental_data/sensory_network_traversal_model_layers.feather",
    "supplemental_data/optic-column-type-assignments-v1.0.xlsx",
    "supplemental_data/male-cns-v1.0-synapse-connection-precision-recall-by-roi.csv",
    "supplemental_data/male-cns-v1.0-synapse-tbar-precision-recall-by-roi.csv",
    "supplemental_data/male-cns-v1.0-traced-synapse-capture-by-roi.csv",
)


def hydrate(run):
    from inventory import REGISTRY, ROOT, WORK, load, save

    run = Path(run).resolve()
    assert run.is_relative_to(WORK.resolve()) and run.parent.name == "SIM-008"
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-008")
    base = ROOT / row["path"]
    lines = (
        subprocess.check_output(
            ["git", "ls-tree", "-l", row["commit"], "--", *FILES],
            cwd=base,
            timeout=30,
        )
        .decode()
        .splitlines()
    )
    entries = []
    for line in lines:
        metadata, name = line.split("\t", 1)
        mode, kind, oid, size = metadata.split()
        assert name in FILES and mode == "100644" and kind == "blob"
        path = run / "source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("wb") as stream:
                subprocess.run(
                    ["git", "cat-file", "blob", oid],
                    cwd=base,
                    stdout=stream,
                    check=True,
                    timeout=180,
                )
        raw = path.read_bytes()
        assert len(raw) == int(size)
        assert hashlib.sha1(b"blob " + size.encode() + b"\0" + raw).hexdigest() == oid
        entries.append(
            {
                "path": name,
                "bytes": len(raw),
                "git_blob": oid,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    assert {x["path"] for x in entries} == set(FILES)
    save(
        run / "pinned-supplements.json",
        {
            "commit": row["commit"],
            "files": entries,
            "scope": "v1.0 supplemental tables, separate from the notebook's v0.9 inputs",
        },
    )
    print("Verified six pinned supplemental tables; upstream unchanged", flush=True)
