"""Add three owner-registry ECAP/SCS pain-outcome leads to NS-14."""

# ruff: noqa: E501 -- exact registry fields and scientific access boundaries are preserved.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"


def locator(trial_id: str, field: str) -> dict[str, str]:
    return {"url": f"https://clinicaltrials.gov/api/v2/studies/{trial_id}", "locator": field}


NEW_TRIALS = [
    {
        "trial_id": "NCT07209514",
        "source_ids": [],
        "registry_status": "ENROLLING_BY_INVITATION",
        "last_update_posted": "2025-10-15",
        "lead_sponsor": "TriCity Research Center",
        "condition": "Painful diabetic peripheral neuropathy",
        "estimated_enrollment": 25,
        "ipd_sharing": "UNDECIDED",
        "registered_primary_outcomes": "Change in VAS pain intensity from baseline to 12 months; trial-end and 1/3/6/12-month measurements registered",
        "registered_secondary_outcomes": "No registered secondary outcome",
        "registered_other_outcomes": "No registered other outcome",
        "ecap_role": "The intervention description specifies Medtronic Inceptiv closed-loop DTM SCS with ECAP-feedback adjustment.",
        "patient_linkage": "not_established_from_registry",
        "data_availability": "registry_metadata_only_no_results",
        "boundary": "Interventional estimated cohort, not released participant data; IPD sharing remains undecided. Distinct diabetic-neuropathy device study, not an EVOKE report.",
        "locators": [
            locator("NCT07209514", "protocolSection.designModule.studyType and enrollmentInfo; statusModule.overallStatus, lastUpdatePostDateStruct.date"),
            locator("NCT07209514", "protocolSection.armsInterventionsModule.interventions[0].description (ECAP feedback and DTM SCS)"),
            locator("NCT07209514", "protocolSection.outcomesModule.primaryOutcomes[0].measure, description, timeFrame"),
            locator("NCT07209514", "protocolSection.ipdSharingStatementModule.ipdSharing; hasResults"),
        ],
    },
    {
        "trial_id": "NCT06377969",
        "source_ids": [],
        "registry_status": "RECRUITING",
        "last_update_posted": "2026-03-11",
        "lead_sponsor": "Stanford University",
        "condition": "Chronic pelvic pain syndrome",
        "estimated_enrollment": 10,
        "ipd_sharing": "NO",
        "registered_primary_outcomes": "Change in 0-10 numerical pain rating at baseline and 3/6/12 months",
        "registered_secondary_outcomes": "Disability, global impression, quality of life, catastrophizing, sleep and social functioning through 12 months",
        "registered_other_outcomes": "No registered other outcome",
        "ecap_role": "The device intervention is explicitly named ECAP-controlled closed-loop spinal cord stimulation.",
        "patient_linkage": "not_established_from_registry",
        "data_availability": "registry_metadata_only_no_results",
        "boundary": "A separate pelvic-pain interventional cohort is registered, but IPD sharing is NO and no ECAP waveform/outcome table or stable patient key is available from the record.",
        "locators": [
            locator("NCT06377969", "protocolSection.designModule.studyType and enrollmentInfo; statusModule.overallStatus, lastUpdatePostDateStruct.date"),
            locator("NCT06377969", "protocolSection.armsInterventionsModule.interventions[0].name and description"),
            locator("NCT06377969", "protocolSection.outcomesModule.primaryOutcomes[0] and secondaryOutcomes"),
            locator("NCT06377969", "protocolSection.ipdSharingStatementModule.ipdSharing; hasResults"),
        ],
    },
    {
        "trial_id": "NCT06533917",
        "source_ids": [],
        "registry_status": "UNKNOWN",
        "last_update_posted": "2024-08-15",
        "lead_sponsor": "The Leeds Teaching Hospitals NHS Trust",
        "condition": "Chronic abdominal pain in title; conditionsModule lists generic Pain",
        "estimated_enrollment": 10,
        "ipd_sharing": "not_registered",
        "registered_primary_outcomes": "Safety/feasibility of ECAP-controlled closed-loop SCS and change in weekly average VAS pain intensity at 12 months",
        "registered_secondary_outcomes": "No registered secondary outcome",
        "registered_other_outcomes": "No registered other outcome",
        "ecap_role": "ECAP-controlled closed-loop SCS appears in the primary-outcome wording; intervention description lists thoracolumbar radiographs and does not specify the controller.",
        "patient_linkage": "not_established_from_registry",
        "data_availability": "registry_metadata_only_no_results",
        "boundary": "Registry record is stale (UNKNOWN status) and internally incomplete about the device. Treat as a candidate protocol only; neither ECAP implementation nor data access is independently confirmed.",
        "locators": [
            locator("NCT06533917", "protocolSection.identificationModule.briefTitle, conditionsModule.conditions, designModule.enrollmentInfo"),
            locator("NCT06533917", "protocolSection.outcomesModule.primaryOutcomes[0:2].measure and timeFrame"),
            locator("NCT06533917", "protocolSection.armsInterventionsModule.interventions[0].description; statusModule.overallStatus and lastUpdatePostDateStruct.date"),
            locator("NCT06533917", "protocolSection.ipdSharingStatementModule absent; hasResults"),
        ],
    },
]


def updated() -> dict:
    audit = json.loads((DATA / "ecap-trial-registry-audit.json").read_text(encoding="utf-8"))
    existing = {trial["trial_id"] for trial in audit["trials"]}
    for trial in NEW_TRIALS:
        if trial["trial_id"] in existing:
            raise ValueError(f"Trial already logged: {trial['trial_id']}")
    audit["trials"].extend(NEW_TRIALS)
    audit["meta"]["trial_count"] = len(audit["trials"])
    audit["meta"]["checked_at"] = DATE
    audit["search_update"] = {
        "checked_at": DATE,
        "source": "ClinicalTrials.gov API v2 interventional ECAP/closed-loop SCS query family, followed by per-record outcome and intervention screening",
        "new_trial_ids": [trial["trial_id"] for trial in NEW_TRIALS],
        "boundary": "Three additional registered cohorts; no participant-linked ECAP and pain data released in these records. Query saturation and future updates remain open.",
    }
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit = updated()
    if not args.apply:
        print(f"Dry run: NS-14 trial count {audit['meta']['trial_count']}")
        return
    snapshot = snapshot_repository(DATA, label="pre-ns14-ecap-trial-extension")
    atomic_write_json(DATA / "ecap-trial-registry-audit.json", audit)
    print(f"NS-14 trial count {audit['meta']['trial_count']}; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
