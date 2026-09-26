"""Place two early ECAP artifact patents in the bounded NS-08/NS-13 map."""

# ruff: noqa: E501 -- patent claim locators and evidence limits are deliberate.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
WO = "https://patents.google.com/patent/WO2010032132A1/en"
US = "https://patents.google.com/patent/US7835804B2/en"


def revised() -> tuple[dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "ecap-scs-audit.json").read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    ids = {item["id"] for item in records["sources"]}
    if not {"S770", "S771"} <= ids:
        raise ValueError("Publish both historical patents first")
    review = audit["ns08_artifact_review"]
    if "historical_patent_sources" in review:
        raise ValueError("Historical patents already audited")
    review["historical_patent_sources"] = ["S770", "S771"]
    review["decision"] += (
        " Earlier WO2010032132A1 claims a waveform-cost/source-separation method in a cochlear ECAP example, "
        "whereas US7835804B2 claims an electrical-equivalent eCAP artifact measurement model. "
        "Neither patent establishes human SCS artifact-removal accuracy or pain outcomes."
    )
    for stream_id in ("NS-08", "NS-13"):
        stream = next(item for item in protocol["search_streams"] if item["id"] == stream_id)
        if set(stream["source_ids"]) & {"S770", "S771"}:
            raise ValueError(f"Patents already linked to {stream_id}")
        stream["source_ids"].extend(["S770", "S771"])
    if any(item["id"] == "NS-RUN-2026-09-24-17" for item in protocol["search_runs"]):
        raise ValueError("Search run already exists")
    protocol["search_runs"].append(
        {
            "id": "NS-RUN-2026-09-24-17",
            "date": "2026-09-24",
            "queries": [
                "early ECAP stimulus artifact removal patent cochlear neural stimulator Strahl",
                "eCAP recording artifact electrical-equivalent model Fridman Karunasiri",
            ],
            "primary_urls": [WO, US],
            "new_mechanism_classes": [
                "cochlear ECAP waveform cost-function artifact separation",
                "electrical-equivalent eCAP artifact measurement model",
            ],
            "direct_drosophila_ecap_scs_analogue_found": False,
            "saturation": False,
        }
    )
    if any("S770" in row["source_ids"] or "S771" in row["source_ids"] for row in matrix["rows"]):
        raise ValueError("Historical patents already in evidence matrix")
    matrix["rows"].append(
        {
            "batch_id": "ns08-historical-patent-review-2026-09-24",
            "claim": "ECAP stimulus-artifact handling predates recent SCS machine-learning patents in distinct cochlear and generic neural-stimulator forms.",
            "target_variable": "ECAP waveform artifact or modeled post-stimulus recording artifact",
            "population_or_data": "Patent disclosures and model examples; no auditable clinical SCS cohort",
            "source_ids": ["S770", "S771"],
            "verified_evidence": "WO2010032132A1 claims 1-7 cover a cost-function stimulation waveform and source separation, with ECAP/cochlear dependents; US7835804B2 claims 1 and 7 cover an electrical-equivalent eCAP artifact model.",
            "limitations": "Patent claims are technical prior art, not measured clinical efficacy or validation. The WO example is cochlear; neither has a Drosophila/connectome transfer chain.",
            "permitted_conclusion": "Use as peripheral historical artifact-removal prior art; do not claim demonstrated SCS performance or pain relief.",
            "locators": [
                {
                    "source_id": "S770",
                    "url": WO,
                    "locator": "Description [0002]-[0011]; claims 1-7",
                },
                {
                    "source_id": "S771",
                    "url": US,
                    "locator": "Abstract; independent claims 1 and 7; dependent claims 3-6",
                },
            ],
        }
    )
    return audit, protocol, matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit, protocol, matrix = revised()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ns08-historical-patent-review")
        atomic_write_json(DATA / "ecap-scs-audit.json", audit)
        atomic_write_json(DATA / "search-protocol.json", protocol)
        atomic_write_json(DATA / "evidence-matrix.json", matrix)
        print(f"Applied historical patent review; snapshot: {snapshot}")
    else:
        print("Dry run: historical patent review ready; NS-08 and NS-13 remain open")


if __name__ == "__main__":
    main()
