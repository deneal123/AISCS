"""Record Betzel's structural cross-species precedent in NS-05."""

# ruff: noqa: E501 -- exact primary sections and inference boundary are retained.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
URL = "https://pmc.ncbi.nlm.nih.gov/articles/PMC5783945/"
DATE = "2026-09-25"


def revised() -> tuple[dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    if not any(item["id"] == "S772" for item in records["sources"]):
        raise ValueError("S772 must be published first")
    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-05")
    if "S772" in stream["source_ids"]:
        raise ValueError("S772 already in NS-05")
    if any(item["id"] == "NS-RUN-2026-09-25-02" for item in protocol["search_runs"]):
        raise ValueError("Search run already exists")
    if any("S772" in row["source_ids"] for row in matrix["rows"]):
        raise ValueError("S772 already in evidence matrix")
    stream["source_ids"].append("S772")
    stream["coverage_note"] = (
        "S772 establishes cross-species structural comparison of mesoscale community motifs in published "
        "inter-areal connectomes. Its human functional-connectivity analysis is within human data; no "
        "Drosophila-to-human dynamical representation, causal-invariant, ECAP or SCS transfer is tested. "
        "Exact/synonym/author search and backward/forward citation screening remain open."
    )
    protocol["search_runs"].append(
        {
            "id": "NS-RUN-2026-09-25-02",
            "date": DATE,
            "queries": [
                "cross-species connectome graph motif Betzel Bassett weighted stochastic blockmodel",
                "10.1038/s41467-017-02681-z Drosophila human inter-areal community motif",
            ],
            "primary_urls": [URL, "https://www.nature.com/articles/s41467-017-02681-z"],
            "new_mechanism_classes": [
                "cross-species inter-areal structural community-motif comparison"
            ],
            "direct_drosophila_ecap_scs_analogue_found": False,
            "saturation": False,
        }
    )
    matrix["rows"].append(
        {
            "batch_id": "ns05-betzel-structural-comparison-2026-09-25",
            "claim": "Cross-species comparison of connectome community motifs predates proposed graph-motif transfer.",
            "target_variable": "Mesoscale assortative, core-periphery and disassortative structural community motifs",
            "population_or_data": "Previously published inter-areal Drosophila, mouse, rat, macaque and human connectomes; human functional connectivity examined separately",
            "source_ids": ["S772"],
            "verified_evidence": "The primary article fits weighted stochastic blockmodels to group-representative human connectomes and repeats structural analyses on non-human inter-areal graphs; its human functional-connectivity comparison appears in a separate Results section.",
            "limitations": "Graph scales differ from neuron-level FlyWire/VNC; no learned cross-species dynamical transfer, causal-invariant test, physical ECAP operator or SCS endpoint.",
            "permitted_conclusion": "Use as structural motif-comparison prior art, not as validation of a Drosophila-to-human ECAP/SCS bridge.",
            "locators": [
                {
                    "source_id": "S772",
                    "url": URL,
                    "locator": "Abstract; Results > The weighted stochastic blockmodel and connectome data sets; Results > Functional relevance; Methods > Connectome data sets",
                }
            ],
        }
    )
    return protocol, matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    protocol, matrix = revised()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ns05-betzel-review")
        atomic_write_json(DATA / "search-protocol.json", protocol)
        atomic_write_json(DATA / "evidence-matrix.json", matrix)
        print(f"Applied S772 NS-05 review; snapshot: {snapshot}")
    else:
        print("Dry run: S772 ready for NS-05; PA-02 remains open")


if __name__ == "__main__":
    main()
