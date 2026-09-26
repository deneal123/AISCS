"""Record the first NS-07 physical ECAP forward-model prior-art pass."""

# ruff: noqa: E501 -- keep scientific locators and model boundaries explicit.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
URL = "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0345287"


def field(value: str | None, locator: str, *, state: str = "reported") -> dict:
    return {
        "state": state,
        "value": value,
        "reason": "Extracted from the publisher full text; limits are stated rather than inferred.",
        "checked_at": DATE,
        "locators": [{"url": URL, "locator": locator}],
    }


def update() -> tuple[dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "ecap-scs-audit.json").read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    if not any(item["id"] == "S764" for item in records["sources"]):
        raise ValueError("S764 must be published before NS-07 review")
    if any(item["source_id"] == "S764" for item in audit["entries"]):
        raise ValueError("S764 is already present in the ECAP audit")
    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-07")
    if stream["status"] != "open" or stream["source_ids"] != ["S105"]:
        raise ValueError("NS-07 stream changed; inspect before updating")
    if any(item["id"] == "NS-RUN-2026-09-24-11" for item in protocol["search_runs"]):
        raise ValueError("NS-07 search run already exists")

    audit["entries"].append({
        "source_id": "S764",
        "extraction": {
            "sample": field(None, "Methods > Simulation model of SCS-induced electric field: anatomical simulation without participants", state="not_applicable"),
            "electrode_geometry": field(
                "Eight-layer human thoracic FEM; traditional eight-contact percutaneous lead versus segmented directional lead; orientation and contact angle varied",
                "Methods > Simulation model of SCS-induced electric field; Fig. 1; Table 1",
            ),
            "stimulation": field(
                "Bipolar monophasic stimulation; COMSOL electric field drives multicompartment dorsal-column fibers; reciprocity maps membrane currents to recording contacts",
                "Methods > Simulation model of SCS-induced electric field; Multi-compartment cable model; Calculation of simulated ECAP signals",
            ),
            "split_unit": field(None, "Methods and Limitations: no enrolled cohort or patient-level train/test split", state="not_applicable"),
            "metrics": field(
                "At 8 mA, simulated E3-E0 ECAP amplitude 244.8 microvolts for the traditional lead and 363.6 microvolts for the directional lead; these are model outputs",
                "Discussion, E3-E0 comparison; Fig. 3B",
            ),
        },
    })
    audit["meta"]["records_count"] = len(audit["entries"])
    audit["ns07_forward_model_review"] = {
        "checked_at": DATE,
        "status": "first_pass_recorded",
        "direct_model_sources": ["S363", "S764"],
        "empirical_ecap_source": "S105",
        "historical_primary_lead": {
            "doi": "10.1111/ner.12965",
            "pmid": "31215720",
            "url": "https://pubmed.ncbi.nlm.nih.gov/31215720/",
            "locator": "Abstract, Methods: finite-element thoracic SCS, multicompartment axons and reciprocity-based recording; full-method extraction and canonical screening pending",
        },
        "decision": "A physical recruitment-to-extracellular ECAP operator is established prior art. S363 is a six-swine preclinical model and S764 is a human-anatomy simulation; neither validates Drosophila transfer or patient-linked SCS outcomes. S105 is an empirical signal-analysis source, not a volume-conductor forward model.",
        "remaining": "Complete exact/synonym/author and backward/forward citation search, screen the Anaya 2019/2020 primary full text and adjacent model families, then run a later dated refresh; do not close NS-07 or PA-04 now.",
    }
    stream["source_ids"] = ["S105", "S363", "S764"]
    stream["status"] = "initial_pass_recorded"
    protocol["search_runs"].append({
        "id": "NS-RUN-2026-09-24-11",
        "date": DATE,
        "queries": [
            "spinal cord stimulation ECAP computational model volume conductor extracellular potential finite element",
            "evoked compound action potential spinal cord stimulation biophysical model electrode geometry reciprocity",
            "Anaya Zander Lempka ECAP computational modeling backward reference search",
        ],
        "primary_urls": [
            URL,
            "https://pubmed.ncbi.nlm.nih.gov/40767809/",
            "https://pubmed.ncbi.nlm.nih.gov/31215720/",
        ],
        "new_mechanism_classes": [],
        "direct_drosophila_ecap_scs_analogue_found": False,
        "saturation": False,
    })
    return audit, protocol


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit, protocol = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ns07-forward-model-review")
        atomic_write_json(DATA / "ecap-scs-audit.json", audit)
        atomic_write_json(DATA / "search-protocol.json", protocol)
        print(f"Applied NS-07 first pass; snapshot: {snapshot}")
    else:
        print("Dry run: S363 and S764 are physical ECAP model analogues; NS-07 remains open")


if __name__ == "__main__":
    main()
