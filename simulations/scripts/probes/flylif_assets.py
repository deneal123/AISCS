"""Prepare an explicit alternate Codex v783 input, not the unidentified paper graph.

Only existing, hash-bound primary exports are read. Derived uncompressed files
live in cache/ so normal post-trial cleanup removes them. No 13 GB skeleton set
is required by the LIF entry point.
"""

import gzip
import hashlib
import shutil
from pathlib import Path

from inventory import REGISTRY, ROOT, load, save
from probes.optic_lobe_assets import prepare_font
from simctl import checked_work

NAMES = {
    "visual_neuron_types.csv.gz": "visual_neuron_types.csv",
    "column_assignment.csv.gz": "column_assignment.csv",
    "connections_princeton_no_threshold.csv.gz": "connections_no_threshold.csv",
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def hydrate(run):
    row = next(x for x in load(REGISTRY)["candidates"] if x["id"] == "SIM-010")
    reference = row["frozen_inputs"]
    manifest = checked_work(ROOT / reference["path"])
    if sha(manifest) != reference["sha256"]:
        raise ValueError("Codex v783 primary manifest changed")
    selected = {
        Path(x["file"]).name: x
        for x in load(manifest)["inputs"]
        if Path(x["file"]).name in NAMES
    }
    if set(selected) != set(NAMES):
        raise ValueError("Alternate Codex input set is incomplete")
    entries = []
    for name, target_name in NAMES.items():
        item = selected[name]
        source = checked_work(manifest.parent / item["file"])
        if item["status"] != "verified" or sha(source) != item["sha256"]:
            raise ValueError("Alternate Codex primary input changed: " + name)
        target = checked_work(run / "cache/flywire" / target_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(source, "rb") as incoming, target.open("wb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, length=1024**2)
        entries.append(
            {
                "primary_file": source.relative_to(ROOT).as_posix(),
                "primary_sha256": item["sha256"],
                "primary_url": item["url"],
                "derived_file": target.relative_to(run).as_posix(),
                "derived_sha256": sha(target),
                "derived_bytes": target.stat().st_size,
            }
        )
    save(
        run / "flylif-inputs.json",
        {
            "materialization": "FAFB v783 Princeton no-threshold (explicit alternate)",
            "author_graph_identity": "not established; not an exact paper reproduction",
            "primary_manifest": reference,
            "network_attempts": 0,
            "inputs": entries,
            "scope": "LIF software trial on a versioned alternate graph; no biological validation",
        },
    )
    prepare_font(run)
