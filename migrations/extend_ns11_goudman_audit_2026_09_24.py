"""Place published S762 in NS-11 without inferring composite thresholds."""

# ruff: noqa: E501 -- exact primary-source boundaries and locators stay explicit.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
URL = "https://pubmed.ncbi.nlm.nih.gov/32910099/"


def field(state: str, value: str | None, reason: str, locator: str) -> dict:
    return {
        "state": state,
        "value": value,
        "reason": reason,
        "checked_at": DATE,
        "locators": [{"url": URL, "locator": locator}],
    }


def update() -> tuple[dict, dict]:
    audit = json.loads((DATA / "ns11-prediction-audit.json").read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    if not any(source["id"] == "S762" for source in records["sources"]):
        raise ValueError("S762 must be published first")
    if any(entry["source_id"] == "S762" for entry in audit["entries"]):
        raise ValueError("S762 already audited")
    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-11")
    lead = next(item for item in audit["meta"]["unindexed_primary_leads"] if item["pmid"] == "32910099")
    audit["entries"].append({
        "source_id": "S762",
        "extraction": {
            "target": field(
                "not_reported", None,
                "The primary abstract lists pain intensity, medication, ODI and EQ-5D changes in the 12-month holistic responder but omits component thresholds and the composite decision rule; later publications must not supply these retrospectively.",
                "Author abstract, Methods: four domains of the holistic responder; numeric thresholds absent",
            ),
            "follow_up": field(
                "reported", "One, three and twelve months after HD-SCS implantation; prediction target is the twelve-month holistic responder",
                "The time points and prediction horizon are explicit in the author abstract.",
                "Author abstract, Methods and Results",
            ),
            "patient_linkage": field(
                "not_reported", None,
                "Baseline and repeated registry outcomes are described for 194 recruited, 185 baseline and 92 still treated at 12 months, but the prediction-analysis denominator and patient-disjoint split are not given; exact predictor-to-target linkage for the classifier remains unverified.",
                "Author abstract, Methods and Results: registry flow and repeated outcomes",
            ),
        },
        "overlap_note": "Discover-registry participants may overlap other high-dose SCS papers by this group; this source is not counted as independent external validation of S756 or related models.",
    })
    audit["entries"].sort(key=lambda item: item["source_id"])
    audit["meta"]["records_count"] = len(audit["entries"])
    audit["meta"]["remaining_source_ids"] = sorted([*audit["meta"]["remaining_source_ids"], "S762"])
    audit["meta"]["unindexed_primary_leads"] = [
        item for item in audit["meta"]["unindexed_primary_leads"] if item["pmid"] != "32910099"
    ]
    audit["meta"]["indexed_primary_leads"] = [
        {**lead, "source_id": "S762", "status": "canonical_card_and_abstract_audit_recorded_full_text_pending"}
    ]
    audit["meta"]["remaining_search_leads"] = [
        item for item in audit["meta"]["remaining_search_leads"]
        if item != "Goudman 2021 full text and canonical source card"
    ]
    audit["meta"]["remaining_search_leads"].append(
        "S762 Goudman 2021 full text for exact holistic-responder thresholds, analysis denominator and split"
    )
    stream["source_ids"] = sorted([*stream["source_ids"], "S762"])
    return audit, protocol


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit, protocol = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ns11-goudman-audit")
        atomic_write_json(DATA / "ns11-prediction-audit.json", audit)
        atomic_write_json(DATA / "search-protocol.json", protocol)
        print(f"Applied NS-11 S762 audit; snapshot: {snapshot}")
    else:
        print("Dry run: 13 NS-11 sources; S762 exact composite target and split remain open")


if __name__ == "__main__":
    main()
