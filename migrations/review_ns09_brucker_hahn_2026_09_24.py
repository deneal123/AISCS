"""Record human ECAP recruitment-estimation evidence and model limits."""

# ruff: noqa: E501 -- primary locators and denominator distinctions are explicit.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
URL = "https://iopscience.iop.org/article/10.1088/1741-2552/aceca4/pdf"


def field(value: str | None, locator: str, *, state: str = "reported") -> dict:
    return {
        "state": state,
        "value": value,
        "reason": "Extracted from the publisher PDF; human observations and model conclusions are separated.",
        "checked_at": DATE,
        "locators": [{"url": URL, "locator": locator}],
    }


def update() -> tuple[dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "ecap-scs-audit.json").read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    if not any(item["id"] == "S767" for item in records["sources"]):
        raise ValueError("S767 must be published first")
    if any(item["source_id"] == "S767" for item in audit["entries"]):
        raise ValueError("S767 already in ECAP audit")
    if any("S767" in row["source_ids"] for row in matrix["rows"]):
        raise ValueError("S767 already in evidence matrix")
    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-09")
    if stream["status"] != "second_pass_recorded" or "S767" in stream["source_ids"]:
        raise ValueError("NS-09 stream changed")
    if any(item["id"] == "NS-RUN-2026-09-24-14" for item in protocol["search_runs"]):
        raise ValueError("Search run already exists")

    audit["entries"].append({
        "source_id": "S767",
        "extraction": {
            "sample": field("56 SCS trial participants, 479 experimental trials; 195 excluded and 284 growth-curve datasets retained from 45 participants", "section 3 Results opening paragraph; Figure 5"),
            "electrode_geometry": field("Conventional eight-contact percutaneous trial leads, usually staggered near T9; stimulation on one end and bipolar ECAP recording on the opposite end", "section 2.1 Experimental data acquisition; Figure 1"),
            "stimulation": field("Cathodic-leading symmetric biphasic pulses at 50 Hz; pulse widths 90-300 microseconds; growth-curve sweeps across posture and electrode configurations", "section 2.1 Experimental data acquisition"),
            "split_unit": field(None, "sections 2.1 and 3: descriptive repeated recordings, without patient-level train/test split", state="not_applicable"),
            "metrics": field("Human supine versus seated ECAP threshold 65.7% lower and growth rate 178.5% higher. Model fixed 25 microvolt ECAP required 94% more activated axons for 4.4 mm versus 2.0 mm dorsal CSF. The latter is simulated, not directly measured in people.", "Abstract Main results; section 3.3; section 4.3 and Figure 8"),
        },
    })
    audit["meta"]["records_count"] = len(audit["entries"])
    audit["ns09_recruitment_review"] = {
        "checked_at": DATE,
        "status": "additional_primary_pass_recorded",
        "human_source": "S767",
        "physical_model_sources": ["S363", "S764", "S766", "S767"],
        "decision": "S767 documents substantial ECAP threshold/growth variability in people and uses a physical model to show that a fixed recorded amplitude need not mean fixed dorsal-column recruitment. Recruitment equivalence is a simulation conclusion, not a directly observed patient-level axon count or pain outcome.",
        "denominator": "56 enrolled participants; 479 trials; 195 trials excluded; 284 growth curves from 45 participants analyzed. Eleven participants had all trials excluded.",
        "remaining": "Complete exact/synonym/author and backward/forward citation screening, including earlier human and animal ECAP threshold studies; later dated refresh required before NS-09 or PA-04 closure.",
    }
    stream["source_ids"] = list(dict.fromkeys([*stream["source_ids"], "S363", "S764", "S766", "S767"]))
    protocol["search_runs"].append({
        "id": "NS-RUN-2026-09-24-14",
        "date": DATE,
        "queries": [
            "ECAP posture pulse width constant amplitude neural recruitment Brucker-Hahn Zander",
            "spinal ECAP growth curve electrode spinal cord distance model patient",
        ],
        "primary_urls": [URL, "https://pubmed.ncbi.nlm.nih.gov/37531954/"],
        "new_mechanism_classes": [],
        "direct_drosophila_ecap_scs_analogue_found": False,
        "saturation": False,
    })
    matrix["rows"].append({
        "batch_id": "ns09-recruitment-review-2026-09-24",
        "claim": "Recorded ECAP amplitude is affected by posture and electrode-to-cord distance, so a fixed ECAP target may not imply fixed recruited-axon count.",
        "target_variable": "Human ECAP threshold/growth rate; simulated activated dorsal-column axons",
        "population_or_data": "56 human SCS trial participants; 284 retained growth curves from 45 people; separate generalized physical model",
        "source_ids": ["S767"],
        "verified_evidence": "Publisher Results reports posture-dependent ECAP metrics; Figure 8 model compares fixed ECAP amplitudes at different CSF thicknesses and finds differing activation counts.",
        "limitations": "The activated-axon count is simulated, not measured in people. Acute trial recordings and a generalized model do not establish chronic pain-response prediction; 11 participants contributed no retained growth curves.",
        "permitted_conclusion": "Use as a neural-recruitment measurement limitation and ECAP modeling comparator; do not equate ECAP amplitude to pain or exact recruitment.",
        "locators": [{"source_id": "S767", "url": URL, "locator": "sections 2.1-2.3, 3 opening paragraph, 3.3, 4.3-4.4; Figures 5 and 8"}],
    })
    return audit, protocol, matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit, protocol, matrix = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ns09-recruitment-review")
        atomic_write_json(DATA / "ecap-scs-audit.json", audit)
        atomic_write_json(DATA / "search-protocol.json", protocol)
        atomic_write_json(DATA / "evidence-matrix.json", matrix)
        print(f"Applied S767 NS-09 review; snapshot: {snapshot}")
    else:
        print("Dry run: S767 NS-09 review ready; PA-04 remains open")


if __name__ == "__main__":
    main()
