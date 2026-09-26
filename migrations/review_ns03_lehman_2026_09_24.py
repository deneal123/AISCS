"""Add the primary Lehman larval defensive-circuit study to NS-03."""

# ruff: noqa: E501 -- retain exact source sections and scientific boundaries.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
URL = "https://www.nature.com/articles/s41467-025-56185-2"
DATE = "2026-09-24"


def field(value: str, section: str, *, boundary: bool = False) -> dict:
    return {
        "state": "reported",
        "value": value,
        "reason": (
            "Conservative inference from source scope; defensive behavior is not subjective pain."
            if boundary
            else "Extracted from the primary publisher full text and JATS."
        ),
        "checked_at": DATE,
        "locators": [{"url": URL, "locator": section}],
    }


def revised() -> tuple[dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "drosophila-nociception-audit.json").read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    if not any(source["id"] == "S769" for source in records["sources"]):
        raise ValueError("Publish S769 before review")
    if any(item["source_id"] == "S769" for item in audit["entries"]):
        raise ValueError("S769 already audited")
    if any(item["id"] == "NS-RUN-2026-09-24-16" for item in protocol["search_runs"]):
        raise ValueError("Search run already exists")
    audit["entries"].append(
        {
            "source_id": "S769",
            "source_role": "primary_experiment",
            "extraction": {
                "stimulus": field(
                    "Third-instar larvae received 50 mN von Frey mechanical stimulation or a 46 °C hot probe; other experiments combined air puff and optogenetic activation.",
                    "Methods > Mechano- and thermo-nociceptive assays; Results Figures 3-4",
                ),
                "neural_response": field(
                    "A19c and TDN connectivity was reconstructed in a separate 6-hour-old larval EM reference. GCaMP6s imaging measured A19c/TDN responses to Basin-2 optogenetic activation, air puff and combined stimulation; these recordings do not directly quantify a subjective state.",
                    "Results > Thoracic and abdominal neurons in the R11A07 line have distinct functions, Figure 6e-h; Relative level of A19c neuron activation, Figure 7f-g; Methods > EM reconstruction",
                ),
                "behavior": field(
                    "Kir2.1 silencing of R11A07 neurons reduced mechanical C-shape/rolling (n=63/60/60 by genotype) but did not change thermal rolling latency (n=70/99/90); startle and escape actions also depended on context.",
                    "Results > R11A07 neurons are required for mechano-nociception, Figure 4a-b; Results Figures 3 and 7",
                ),
                "pain_boundary": field(
                    "Anatomy, calcium response and defensive actions are distinct measurements in larvae. The reference EM specimen differs from the behavioral animals; neither rolling nor calcium activity measures subjective pain or human SCS response.",
                    "Methods > EM reconstruction and Mechano- and thermo-nociceptive assays; Discussion",
                    boundary=True,
                ),
            },
        }
    )
    audit["entries"].sort(key=lambda item: item["source_id"])
    audit["meta"]["records_count"] = len(audit["entries"])
    audit["meta"]["candidate_source_ids"].append("S769")
    lead = {
        "title": "Neural circuits underlying context-dependent competition between defensive actions in Drosophila larvae",
        "url": URL,
        "locator": "Results Figure 4 and Methods: 50 mN and 46 °C nociceptive assays; Figures 6-7 calcium imaging and circuit perturbations",
        "status": "primary_full_text_canonical_card_and_audit_recorded",
        "source_id": "S769",
    }
    audit["meta"]["indexed_primary_leads"].append(lead)
    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-03")
    stream["source_ids"].append("S769")
    stream["indexed_primary_leads"].append(lead)
    stream["coverage_note"] = (
        "Eighteen canonical candidates now include original experiments, protocols, a dataset description and reviews. "
        "All 18 have stimulus, neural-response, behavior and pain-boundary extraction. S769 adds context-dependent "
        "mechanical defensive-action circuitry with distinct EM reference and behavioral animals. Backward and "
        "forward citation screening remains open."
    )
    protocol["search_runs"].append(
        {
            "id": "NS-RUN-2026-09-24-16",
            "date": DATE,
            "queries": [
                "Drosophila larvae nociceptive defensive circuit 2025 connectome",
                "context-dependent competition defensive actions Drosophila nociception 10.1038/s41467-025-56185-2",
            ],
            "primary_urls": [URL, "https://pubmed.ncbi.nlm.nih.gov/39875414/"],
            "new_mechanism_classes": ["context-dependent larval startle/escape competition"],
            "direct_drosophila_ecap_scs_analogue_found": False,
            "saturation": False,
        }
    )
    matrix["rows"].append(
        {
            "batch_id": "ns03-lehman-primary-review-2026-09-24",
            "claim": "Larval defensive-action selection depends on sensory context and A19c/TDN circuit interactions.",
            "target_variable": "Mechanical C-shape/rolling, thermal rolling latency, startle/escape action, A19c/TDN calcium response",
            "population_or_data": "Drosophila third-instar experimental larvae and a separate 6-hour-old larval EM reference",
            "source_ids": ["S769"],
            "verified_evidence": "Figure 4 reports a selective mechanical behavioral effect after R11A07 silencing; Figures 6-7 and Methods separately report calcium imaging and EM connectivity.",
            "limitations": "No subjective-pain readout, connectome-constrained dynamical model, human ECAP or SCS outcome; EM and behavior are from different animals.",
            "permitted_conclusion": "Use as a circuit-level biological comparator for larval defensive behavior, not as a human pain or SCS validation.",
            "locators": [
                {
                    "source_id": "S769",
                    "url": URL,
                    "locator": "Results Figures 4, 6 and 7; Methods > EM reconstruction and nociceptive assays",
                }
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
        snapshot = snapshot_repository(DATA, label="pre-ns03-lehman-review")
        atomic_write_json(DATA / "drosophila-nociception-audit.json", audit)
        atomic_write_json(DATA / "search-protocol.json", protocol)
        atomic_write_json(DATA / "evidence-matrix.json", matrix)
        print(f"Applied NS-03 Lehman review; snapshot: {snapshot}")
    else:
        print("Dry run: S769 ready for NS-03; citation screening remains open")


if __name__ == "__main__":
    main()
