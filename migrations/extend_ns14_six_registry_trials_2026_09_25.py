"""Add six independently checked ECAP/SCS trial registrations to NS-14."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
ROWS = [
    (
        "NCT06246526", "RECRUITING", "2026-06-23", "Saint Francis Hospital", "NO",
        "VAS pain from baseline to 12 months",
        "PROMIS-29 from baseline to 12 months",
        "Evoke intervention description says it measures and records spinal-cord activation.",
    ),
    (
        "NCT06413277", "RECRUITING", "2024-05-14",
        "Ainsworth Institute of Pain Management", "NO",
        "Pelvic-pain responder proportion at >=50% and >=80% relief at 12 months",
        "Pain impact, quality of life, safety and device settings at 12 months",
        "Title, summary and outcome descriptions name ECAP-controlled closed-loop SCS.",
    ),
    (
        "NCT06775535", "RECRUITING", "2025-01-15", "Karel Hanssens", "NO",
        "Change in stimulation sensation at 6 months",
        "NRS pain at baseline and 3, 6 and 12 months after implant",
        "Intervention names ECAP-controlled closed-loop SCS and recording of ECAPs.",
    ),
    (
        "NCT07267715", "NOT_YET_RECRUITING", "2025-12-05",
        "Dustin Reynolds, MD", "UNDECIDED",
        "Evoke neural-panel metrics derived from ECAP, through 30 days",
        "Pain Locus of Control, NRS and PROMIS-29+2 through 30 days",
        "Primary outcome names an ECAP-derived Evoke neural panel; no released linkage.",
    ),
    (
        "NCT07413731", "RECRUITING", "2026-02-17", "Brai²n", "NO",
        "ECAP amplitude as spinal-cord sensitivity through 1 month after implant",
        "VAS pain intensity and medication intake through 1 month after implant",
        "Intervention description names Evoke ECAP-controlled closed-loop SCS.",
    ),
    (
        "NCT07502612", "RECRUITING", "2026-03-31", "Brai²n", "NO",
        "ECAP amplitude as spinal-cord sensitivity through 6 months after implant",
        "VAS pain intensity, medication intake and activity through 6 months",
        "Evoke closed-loop SCS and ECAP amplitude are registered; "
        "cohort overlap with NCT07413731 is unverified.",
    ),
]


def main() -> None:
    audit = json.loads(
        (DATA / "ecap-trial-registry-audit.json").read_text(encoding="utf-8")
    )
    existing = {row["trial_id"] for row in audit["trials"]}
    if any(row[0] in existing for row in ROWS):
        raise ValueError("One or more trial registrations are already audited")
    for trial_id, status, updated, sponsor, ipd, primary, secondary, role in ROWS:
        url = f"https://clinicaltrials.gov/api/v2/studies/{trial_id}"
        audit["trials"].append({
            "trial_id": trial_id,
            "source_ids": [],
            "registry_status": status,
            "last_update_posted": updated,
            "lead_sponsor": sponsor,
            "ipd_sharing": ipd,
            "registered_primary_outcomes": primary,
            "registered_secondary_outcomes": secondary,
            "registered_other_outcomes": "No other outcome asserted in this review",
            "ecap_role": role,
            "patient_linkage": "not_established_from_registry",
            "data_availability": "registry_metadata_only_no_results",
            "boundary": "Registered ECAP and pain measures do not provide a downloadable "
            "participant-linked waveform/outcome table. Cohort independence from "
            "other registrations has not been demonstrated.",
            "locators": [
                {
                    "url": url,
                    "locator": "protocolSection.identificationModule; statusModule; "
                    "sponsorCollaboratorsModule.leadSponsor",
                },
                {
                    "url": url,
                    "locator": "protocolSection.armsInterventionsModule.interventions; "
                    "outcomesModule.primaryOutcomes and secondaryOutcomes",
                },
                {
                    "url": url,
                    "locator": "protocolSection.ipdSharingStatementModule.ipdSharing; "
                    "hasResults=false",
                },
            ],
        })
    audit["meta"]["trial_count"] = len(audit["trials"])
    audit.setdefault("search_update_history", []).append(audit["search_update"])
    audit["search_update"] = {
        "checked_at": "2026-09-25",
        "source": "ClinicalTrials.gov API v2 exact/synonym ECAP-guided "
        "SCS queries and six per-record checks",
        "new_trial_ids": [row[0] for row in ROWS],
        "boundary": "Six additional registrations, no results or participant-linked "
        "ECAP/pain release. Query saturation and later dated update remain open. "
        "NCT07413731 and NCT07502612 have the same sponsor; "
        "independent cohorts are not assumed.",
    }
    review = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "new_trial_ids": [row[0] for row in ROWS],
        "official_api_urls": [
            f"https://clinicaltrials.gov/api/v2/studies/{row[0]}" for row in ROWS
        ],
        "decision": "add_registry_metadata_only",
        "boundary": audit["search_update"]["boundary"],
    }
    snapshot = snapshot_repository(DATA, label="pre-ns14-six-trial-extension")
    atomic_write_json(DATA / "ecap-trial-registry-audit.json", audit)
    atomic_write_json(DATA / "ns14-six-trial-extension-2026-09-25.json", review)
    print(f"Added six registry rows; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
