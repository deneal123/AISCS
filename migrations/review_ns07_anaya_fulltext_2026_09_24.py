"""Record primary full-text extraction for Anaya's ECAP forward model."""

# ruff: noqa: E501 -- exact primary locators and scientific limits are required.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
URL = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/PMC6920600/unicode"


def field(value: str | None, locator: str, *, state: str = "reported") -> dict:
    return {
        "state": state,
        "value": value,
        "reason": "Extracted from the PMC author manuscript, with model outputs separated from clinical evidence.",
        "checked_at": DATE,
        "locators": [{"url": URL, "locator": locator}],
    }


def update() -> tuple[dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "ecap-scs-audit.json").read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    if not any(item["id"] == "S766" for item in records["sources"]):
        raise ValueError("S766 must be published first")
    if any(item["source_id"] == "S766" for item in audit["entries"]):
        raise ValueError("S766 already in ECAP audit")
    if any("S766" in row["source_ids"] for row in matrix["rows"]):
        raise ValueError("S766 already in evidence matrix")
    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-07")
    if stream["source_ids"] != ["S105", "S363", "S764"]:
        raise ValueError("NS-07 source set changed")
    if any(item["id"] == "NS-RUN-2026-09-24-13" for item in protocol["search_runs"]):
        raise ValueError("Search run already recorded")

    audit["entries"].append({
        "source_id": "S766",
        "extraction": {
            "sample": field(None, "Methods and Study limitations: canonical simulation; Figure 2C uses one previously published clinical trace", state="not_applicable"),
            "electrode_geometry": field("Lower-thoracic human-anatomy FEM, eight-contact percutaneous epidural lead, caudal C7 stimulation and inactive recording contacts referenced to rostral C0", "Methods > FEM of SCS; Calculation of ECAP recordings; Figure 1"),
            "stimulation": field("Current-controlled monopolar cathodic stimulation, 1-10 mA, 50 Hz, 210 microseconds; COMSOL resistive volume conductor and NEURON dorsal-column axons; reciprocity maps membrane currents to lead voltages", "Methods > FEM of SCS; Assessment of direct axonal response; Calculation of ECAP recordings"),
            "split_unit": field(None, "Methods: simulation; no patient-level train/test split", state="not_applicable"),
            "metrics": field("Figure 2C: published clinical versus model P2-N1 amplitude 200 versus 216 microvolts at assumed discomfort threshold; triphasic morphology and similar latency. This is a comparator, not held-out-patient validation.", "Results > Model-based ECAP recordings, Figure 2C; Study limitations"),
        },
    })
    audit["meta"]["records_count"] = len(audit["entries"])
    review = audit["ns07_forward_model_review"]
    review["direct_model_sources"] = ["S363", "S764", "S766"]
    review["historical_primary_lead"] = {
        "source_id": "S766",
        "doi": "10.1111/ner.12965",
        "pmid": "31215720",
        "url": URL,
        "locator": "Methods > FEM of SCS; Multicompartment cable model; Calculation of ECAP recordings; Results Figure 2C; Study limitations",
        "status": "full_author_manuscript_checked",
    }
    review["decision"] = "S766 directly establishes the FEM-to-axon-to-reciprocity ECAP observation chain as prior art, with a published human trace comparator. Its assumed activation thresholds and canonical anatomy do not establish patient-independent accuracy, pain intensity or Drosophila transfer. S363 and S764 provide adjacent model evidence; S105 is empirical signal analysis."
    review["remaining"] = "Complete exact/synonym/author and backward/forward citation screening, including adjacent model families and patents; run a later dated refresh before closing NS-07 or PA-04."
    stream["source_ids"] = ["S105", "S363", "S764", "S766"]
    protocol["search_runs"].append({
        "id": "NS-RUN-2026-09-24-13",
        "date": DATE,
        "queries": [
            "Anaya Zander Graham Sankarasubramanian Lempka evoked potentials computational model full text",
            "PMC6920600 FEM sensory axon reciprocity clinical ECAP Figure 2C limitations",
        ],
        "primary_urls": [URL, "https://pubmed.ncbi.nlm.nih.gov/31215720/"],
        "new_mechanism_classes": [],
        "direct_drosophila_ecap_scs_analogue_found": False,
        "saturation": False,
    })
    matrix["rows"].append({
        "batch_id": "ns07-anaya-fulltext-2026-09-24",
        "claim": "A physical dorsal-column recruitment-to-recorded-ECAP operator is established SCS prior art.",
        "target_variable": "Simulated ECAP P2-N1 amplitude, shape and conduction velocity",
        "population_or_data": "Literature-based canonical lower-thoracic human model; one previously published clinical trace comparator",
        "source_ids": ["S766"],
        "verified_evidence": "Methods couple a finite-element conductor to multicompartment sensory axons and apply reciprocity to each inactive recording contact. Figure 2C compares model and published clinical waveforms (216 and 200 microvolts P2-N1).",
        "limitations": "Thresholds are assumed from activation fractions; anatomy and lead placement are canonical. No patient-level external test, Drosophila transfer or clinical pain-outcome assessment.",
        "permitted_conclusion": "Use as direct physical ECAP forward-model prior art and a simulation comparator, not as proof of clinical prediction.",
        "locators": [{"source_id": "S766", "url": URL, "locator": "Methods > FEM of SCS, Multicompartment cable model, Calculation of ECAP recordings; Results Figure 2C; Study limitations"}],
    })
    return audit, protocol, matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit, protocol, matrix = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ns07-anaya-fulltext-review")
        atomic_write_json(DATA / "ecap-scs-audit.json", audit)
        atomic_write_json(DATA / "search-protocol.json", protocol)
        atomic_write_json(DATA / "evidence-matrix.json", matrix)
        print(f"Applied S766 full-text audit; snapshot: {snapshot}")
    else:
        print("Dry run: S766 full-text audit ready; NS-07 and PA-04 remain open")


if __name__ == "__main__":
    main()
