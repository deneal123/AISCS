"""Record what the S740 primary methods establish about matrix provenance."""

# ruff: noqa: E501 -- keep exact source locators and provenance boundaries readable.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
JATS = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13142387/fullTextXML"
TREE = "https://api.github.com/repos/smpuglie/Pugliese_2026/git/trees/10e7661bf414ba7b4c2edf795cd36d0f878c17c0?recursive=1"


def update() -> dict:
    audit = json.loads((DATA / "drosophila-connectome-audit.json").read_text(encoding="utf-8"))
    walking = next(item for item in audit["entries"] if item["source_id"] == "S740")
    if "upstream_provenance_review" in walking:
        raise ValueError("S740 provenance review already applied")
    matrices = {item["dataset"]: item for item in walking["input_matrix_artifacts"]}
    if set(matrices) != {"MANC", "FANC", "mCNS", "BANC"}:
        raise ValueError("S740 matrix set changed")
    if any(item["upstream_release"]["state"] != "not_reported" for item in matrices.values()):
        raise ValueError("S740 upstream release state changed")

    walking["upstream_provenance_review"] = {
        "checked_at": DATE,
        "primary_full_text": {
            "url": JATS,
            "locator": "Methods > VNC connectome datasets, all paragraphs",
            "finding": "Four named datasets and extraction rules are reported, but no neuPrint dataset-version or CAVE materialization identifier is attached to the four simulation input matrices.",
        },
        "dataset_access": [
            {
                "dataset": "MANC",
                "interface": "neuPrint",
                "locator": "Methods > VNC connectome datasets, first paragraph: MANC front-leg subnetwork selection",
            },
            {
                "dataset": "FANC",
                "interface": "CAVE annotation tables",
                "annotation_table_versions": ["motor neuron table v7", "left t1 local premotor table v6"],
                "version_boundary": "v7 and v6 identify annotation tables, not the FANC segmentation materialization or synapse-table release.",
                "locator": "Methods > VNC connectome datasets, FANC paragraph: 803-neuron left-front-leg network",
            },
            {
                "dataset": "mCNS",
                "interface": "neuPrint",
                "locator": "Methods > VNC connectome datasets, mCNS paragraph: consensusNt and VNC-region synapses",
            },
            {
                "dataset": "BANC",
                "interface": "CAVE/codex annotation table",
                "locator": "Methods > VNC connectome datasets, BANC paragraph: VNC bounding box and neurotransmitter annotations",
            },
        ],
        "author_repository_tree": {
            "url": TREE,
            "locator": "Recursive tree at commit 10e7661: configs/experiment, notebooks and src/data; processed matrices and simulation configs are present; no upstream query/export script or pinned materialization manifest is identified in that tree.",
            "boundary": "A repository tree screen cannot prove how the matrices were originally exported; absence of a lineage manifest is not evidence for a particular upstream release.",
        },
        "decision": "Retain not_reported for all four upstream releases until an author manifest, export query or matching dataset snapshot supplies exact lineage.",
    }
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s740-input-provenance-review")
        atomic_write_json(DATA / "drosophila-connectome-audit.json", audit)
        print(f"Applied S740 input provenance review; snapshot: {snapshot}")
    else:
        print("Dry run: S740 methods and author tree screened; four upstream releases remain not_reported")


if __name__ == "__main__":
    main()
