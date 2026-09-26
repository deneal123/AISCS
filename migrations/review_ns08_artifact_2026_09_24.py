"""Record a primary-checked NS-08 artifact-removal prior-art pass."""

# ruff: noqa: E501 -- primary locators and study boundaries stay explicit.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
URL = "https://www.frontiersin.org/journals/pain-research/articles/10.3389/fpain.2023.1072786/full"


def field(value: str | None, locator: str, *, state: str = "reported") -> dict:
    return {
        "state": state,
        "value": value,
        "reason": "Checked against the publisher full text; repeated observations are distinguished from participants.",
        "checked_at": DATE,
        "locators": [{"url": URL, "locator": locator}],
    }


def update() -> tuple[dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "ecap-scs-audit.json").read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    if not any(item["id"] == "S765" for item in records["sources"]):
        raise ValueError("S765 must be published first")
    if any(item["source_id"] == "S765" for item in audit["entries"]):
        raise ValueError("S765 already audited")
    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-08")
    if stream["source_ids"] != ["S159", "S746"] or stream["status"] != "initial_pass_recorded":
        raise ValueError("NS-08 stream changed; inspect before updating")
    if any(item["id"] == "NS-RUN-2026-09-24-12" for item in protocol["search_runs"]):
        raise ValueError("NS-08 search run already exists")
    if any("S765" in row["source_ids"] for row in matrix["rows"]):
        raise ValueError("S765 already in evidence matrix")

    audit["entries"].append({
        "source_id": "S765",
        "extraction": {
            "sample": field("Two human chronic-pain trial participants; 20 repeated observations across visits and stimulation settings", "Methods 3.1 Participants; Methods 3.4.5 Statistics, Table 3"),
            "electrode_geometry": field("Two externalized percutaneous eight-contact epidural leads offset by 1-2 contacts; caudal stimulation and cephalad recording", "Methods 3.1-3.3; Discussion 5.1"),
            "stimulation": field("Biphasic interleaved stimulation; anodic and cathodic evoked responses analyzed separately; artifact fits on 0.375-4 ms poststimulus average", "Methods 3.3 and 3.4.2-3.4.3"),
            "split_unit": field("20 observations are one or more concatenated trials per participant, visit and setting; no held-out-patient test", "Methods 3.1 and 3.4.5, Table 3"),
            "metrics": field("Double exponential gave best artifact fit; polynomial gave similar N1 time and P2-N1 amplitude with shorter fitting time in the tested recordings", "Results 4.1.1, Figure 5; Discussion 5.3"),
        },
    })
    audit["meta"]["records_count"] = len(audit["entries"])
    audit["ns08_artifact_review"] = {
        "checked_at": DATE,
        "status": "additional_primary_pass_recorded",
        "direct_sources": ["S159", "S765"],
        "patent_source": "S746",
        "decision": "S765 establishes curve-fit artifact subtraction and polarity-dependent ECAP distortion as prior art on human SCS recordings. It is a two-person technical comparison, not evidence of patient-independent performance or analgesic outcome prediction.",
        "remaining": "Complete exact/synonym/author search and backward/forward citations across publisher, IEEE and patent sources; run a later dated refresh before claiming saturation.",
    }
    stream["source_ids"] = ["S159", "S746", "S765"]
    protocol["search_runs"].append({
        "id": "NS-RUN-2026-09-24-12",
        "date": DATE,
        "queries": [
            "spinal cord stimulation ECAP stimulation artifact removal exponential polynomial",
            "Ramadan Konig Zhang Ross Netoff Darrow ECAP artifact backward references",
            "SCS evoked compound action potential artifact cancellation IEEE publisher patent",
        ],
        "primary_urls": [URL, "https://pubmed.ncbi.nlm.nih.gov/41605141/"],
        "new_mechanism_classes": [],
        "direct_drosophila_ecap_scs_analogue_found": False,
        "saturation": False,
    })
    matrix["rows"].append({
        "batch_id": "ns08-artifact-review-2026-09-24",
        "claim": "Curve-fit removal of SCS stimulation artifact from human ECAP recordings is prior art.",
        "target_variable": "Artifact fit, ECAP N1 timing and P2-N1 amplitude",
        "population_or_data": "Two chronic-pain SCS trial participants; 20 repeated recording observations",
        "source_ids": ["S765"],
        "verified_evidence": "Publisher Methods 3.4.3 and Results 4.1.1 compare single and double exponential fits with a second-order polynomial after recording-average subtraction.",
        "limitations": "No held-out patient or clinical pain-outcome assessment; fitting can bias the inferred neural response, and opposite-polarity averaging can alter ECAP morphology.",
        "permitted_conclusion": "Use as human-recording artifact-removal prior art and signal-processing comparator only.",
        "locators": [{"source_id": "S765", "url": URL, "locator": "Methods 3.1, 3.4.3-3.4.5; Results 4.1.1; Discussion 5.3"}],
    })
    return audit, protocol, matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit, protocol, matrix = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ns08-artifact-review")
        atomic_write_json(DATA / "ecap-scs-audit.json", audit)
        atomic_write_json(DATA / "search-protocol.json", protocol)
        atomic_write_json(DATA / "evidence-matrix.json", matrix)
        print(f"Applied NS-08 primary pass; snapshot: {snapshot}")
    else:
        print("Dry run: S765 ready for NS-08 audit; PA-04 remains open")


if __name__ == "__main__":
    main()
