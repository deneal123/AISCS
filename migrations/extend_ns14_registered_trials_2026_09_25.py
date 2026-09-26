"""Extend the official ECAP/outcome registry audit with two direct trials."""

# ruff: noqa: E501 -- exact registry outcome descriptions and field paths.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
TRIALS = [
    {
        "trial_id": "NCT04627974",
        "source_ids": [],
        "registry_status": "ACTIVE_NOT_RECRUITING",
        "last_update_posted": "2026-05-15",
        "lead_sponsor": "Saluda Medical Pty Ltd",
        "ipd_sharing": "NO",
        "registered_primary_outcomes": "Percent change in VAS pain at 3 months post-implant",
        "registered_secondary_outcomes": "Device/procedure adverse events and ECAPs measured by the Evoke SCS System through 60 months post-implant",
        "registered_other_outcomes": "No registered other outcome",
        "patient_linkage": "not_established_from_registry",
        "data_availability": "registry_metadata_only",
        "boundary": "ECAP and pain are registered in one follow-up study; no participant-level waveform/outcome package or linkage key is provided. IPD sharing is NO.",
    },
    {
        "trial_id": "NCT06229470",
        "source_ids": [],
        "registry_status": "ACTIVE_NOT_RECRUITING",
        "last_update_posted": "2026-08-27",
        "lead_sponsor": "Saluda Medical Pty Ltd",
        "ipd_sharing": "NO",
        "registered_primary_outcomes": "Change in ECAPs measured by the Evoke SCS System through 6 months post-implant",
        "registered_secondary_outcomes": "Change in VAS pain, PROMIS-29+2 and PROMIS-10 Global Health through 6 months post-implant",
        "registered_other_outcomes": "No registered other outcome",
        "patient_linkage": "not_established_from_registry",
        "data_availability": "registry_metadata_only",
        "boundary": "Registered ECAP and clinical outcomes do not establish downloadable per-patient data, a linkage key or independent prognostic validation. IPD sharing is NO.",
    },
]


def updated() -> tuple[dict, dict]:
    audit = json.loads((DATA / "ecap-trial-registry-audit.json").read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    if audit["meta"]["trial_count"] != 3 or any(item["trial_id"] in {x["trial_id"] for x in TRIALS} for item in audit["trials"]):
        raise ValueError("NS-14 trial audit changed")
    if any(run["id"] == "NS-RUN-2026-09-25-09" for run in protocol["search_runs"]):
        raise ValueError("NS-14 search run already recorded")
    for item in TRIALS:
        url = f"https://clinicaltrials.gov/api/v2/studies/{item['trial_id']}"
        item["locators"] = [
            {"url": url, "locator": "protocolSection.statusModule.overallStatus and lastUpdatePostDateStruct.date"},
            {"url": url, "locator": "protocolSection.sponsorCollaboratorsModule.leadSponsor"},
            {"url": url, "locator": "protocolSection.outcomesModule.primaryOutcomes, secondaryOutcomes, otherOutcomes"},
            {"url": url, "locator": "protocolSection.ipdSharingStatementModule.ipdSharing"},
        ]
    audit["trials"].extend(TRIALS)
    audit["meta"]["trial_count"] = len(audit["trials"])
    audit["remaining"] = [
        "Screen remaining official registry hits by exact/synonym/owner queries, including withdrawn and prospective studies",
        "Link any published article to its registration without double-counting trial families",
        "Owner confirmation of patient-linked ECAP and outcome fields, consent and data access",
        "Later dated registry update",
    ]
    protocol["search_runs"].append({
        "id": "NS-RUN-2026-09-25-09",
        "date": DATE,
        "queries": ["evoked compound action potential spinal cord stimulation", "ECAP closed loop spinal cord stimulation", "Saluda Evoke ECAP"],
        "primary_urls": [f"https://clinicaltrials.gov/api/v2/studies/{item['trial_id']}" for item in TRIALS],
        "new_mechanism_classes": [],
        "direct_drosophila_ecap_scs_analogue_found": False,
        "saturation": False,
    })
    stream = next(s for s in protocol["search_streams"] if s["id"] == "NS-14")
    stream["coverage_note"] = "Five official ECAP/SCS trial registrations are audited, including NCT04627974 and NCT06229470 with registered ECAP and VAS/PROMIS outcomes. Registry fields do not establish downloadable patient-linked waveforms/outcomes; broader screening, article linkage and later update remain open."
    return protocol, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    protocol, audit = updated()
    if not args.apply:
        print("Dry run: two further NS-14 official trial registrations")
        return
    snapshot = snapshot_repository(DATA, label="pre-ns14-two-trial-extension")
    atomic_write_json(DATA / "search-protocol.json", protocol)
    atomic_write_json(DATA / "ecap-trial-registry-audit.json", audit)
    print(f"Extended NS-14 trial audit; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
