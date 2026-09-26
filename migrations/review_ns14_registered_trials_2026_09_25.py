"""Record a bounded primary ClinicalTrials.gov NS-14 registry pass."""

# ruff: noqa: E501 -- preserve official registry field paths and outcome windows.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"


def trial(nct: str, source_ids: list[str], status: str, posted: str, sponsor: str, ipd: str, primary: str, secondary: str, other: str, boundary: str) -> dict:
    url = f"https://clinicaltrials.gov/api/v2/studies/{nct}"
    return {
        "trial_id": nct, "source_ids": source_ids,
        "registry_status": status, "last_update_posted": posted,
        "lead_sponsor": sponsor, "ipd_sharing": ipd,
        "registered_primary_outcomes": primary,
        "registered_secondary_outcomes": secondary,
        "registered_other_outcomes": other,
        "patient_linkage": "not_established_from_registry",
        "data_availability": "registry_metadata_only",
        "boundary": boundary,
        "locators": [
            {"url": url, "locator": "protocolSection.statusModule.overallStatus and lastUpdatePostDateStruct.date"},
            {"url": url, "locator": "protocolSection.sponsorCollaboratorsModule.leadSponsor"},
            {"url": url, "locator": "protocolSection.outcomesModule.primaryOutcomes, secondaryOutcomes, otherOutcomes"},
            {"url": url, "locator": "protocolSection.ipdSharingStatementModule.ipdSharing"},
        ],
    }


TRIALS = [
    trial(
        "NCT02924129", ["S779", "S780", "S781"], "COMPLETED", "2024-01-03",
        "Saluda Medical Americas, Inc.", "NO",
        "Composite endpoint success at 3 months",
        "Leg/back VAS changes and at least 80% overall pain reduction at 3 months, among nine registered secondary outcomes",
        "No registered other outcome",
        "The registry names clinical response and ECAP-controlled therapy but supplies no downloadable per-patient ECAP waveform/outcome table; article request wording and registry IPD=NO disagree.",
    ),
    trial(
        "NCT04319887", ["S237"], "COMPLETED", "2024-12-31",
        "Saluda Medical Pty Ltd", "NO",
        "ECAPs measured by the Evoke SCS system at 12 months post-implant",
        "No registered secondary outcome",
        "Change in pain, PROMIS-29, PROMIS-10 Global, POMS, PGIC and therapy satisfaction at end of trial and 1/3/6/12/18/24 months post-implant",
        "ECAP and pain outcomes are registered in one trial, but the registry does not specify a released participant key or waveforms; IPD=NO.",
    ),
    trial(
        "NCT04938245", ["S105"], "RECRUITING", "2025-12-17",
        "University of Minnesota", "YES",
        "Feasibility assessed by enrollment at 2 weeks",
        "Acceptability assessed by survey at 2 weeks",
        "Correlation of ECAP peak-to-peak signals with programming parameters and correlation of ECAP with pain relief, both at 2 weeks; stability and intraoperative reliability also registered",
        "A future anonymized deposit is promised; no exact-ID Zenodo accession was found on 2026-09-25. Registered ECAP/pain correlation does not prove patient-linked raw data are accessible.",
    ),
]


def updated() -> tuple[dict, dict]:
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    stream = next(s for s in protocol["search_streams"] if s["id"] == "NS-14")
    if stream["source_ids"] or any(r["id"] == "NS-RUN-2026-09-25-06" for r in protocol["search_runs"]):
        raise ValueError("NS-14 pass already recorded")
    records = {r["id"] for r in json.loads((DATA / "records.json").read_text(encoding="utf-8"))["sources"]}
    source_ids = sorted({source_id for item in TRIALS for source_id in item["source_ids"]})
    if not set(source_ids) <= records:
        raise ValueError("Unpublished source ID in trial audit")
    stream["source_ids"] = source_ids
    stream["status"] = "initial_pass_recorded"
    stream["coverage_note"] = "A first official-registry pass links NCT02924129, NCT04319887 and NCT04938245 to existing primary article cards. Registered ECAP and clinical outcomes are distinguished from a downloadable participant-linked data package. Broader exact/synonym/owner searches, backward/forward snowballing and later update remain open."
    protocol["search_runs"].append({
        "id": "NS-RUN-2026-09-25-06", "date": DATE,
        "queries": ["NCT02924129 EVOKE ClinicalTrials.gov", "NCT04319887 ECAP ClinicalTrials.gov", "NCT04938245 Improving Spinal Cord Stimulation With ECAPS ClinicalTrials.gov"],
        "primary_urls": [f"https://clinicaltrials.gov/api/v2/studies/{item['trial_id']}" for item in TRIALS],
        "new_mechanism_classes": [], "direct_drosophila_ecap_scs_analogue_found": False,
        "saturation": False,
    })
    audit = {
        "meta": {
            "schema_version": "1.0.0", "checked_at": DATE,
            "status": "in_progress", "trial_count": len(TRIALS),
            "scope": "NS-14 official registrations that mention ECAP telemetry and clinical outcomes",
            "decision": "registry_outcomes_identified_patient_linkage_and_data_access_unconfirmed",
        },
        "trials": TRIALS,
        "remaining": ["Exact/synonym/owner searches for additional registered studies", "Owner confirmation of patient-linked ECAP and outcome fields", "Later dated registry update"],
    }
    return protocol, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    protocol, audit = updated()
    if not args.apply:
        print("Dry run: three official NS-14 trial records; search remains open")
        return
    snapshot = snapshot_repository(DATA, label="pre-ns14-first-registry-pass")
    atomic_write_json(DATA / "search-protocol.json", protocol)
    atomic_write_json(DATA / "ecap-trial-registry-audit.json", audit)
    print(f"Recorded NS-14 registry pass; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
