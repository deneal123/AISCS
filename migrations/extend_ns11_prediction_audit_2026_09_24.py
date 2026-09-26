"""Extend the open NS-11 audit with primary target, horizon and linkage evidence."""

# ruff: noqa: E501 -- primary URLs and exact extraction statements are retained.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
AUDIT = DATA / "ns11-prediction-audit.json"
DATE = "2026-09-24"
NATURE = "https://www.nature.com/articles/s41598-025-92111-8"
OUNAJIM = "https://pmc.ncbi.nlm.nih.gov/articles/PMC8538165/"
MEKHAIL = "https://pubmed.ncbi.nlm.nih.gov/37061895/"
POPE = "https://link.springer.com/article/10.1007/s40122-024-00631-4"
KABIR = "https://pubmed.ncbi.nlm.nih.gov/42524811/"


def field(value: str, url: str, locator: str, reason: str) -> dict:
    return {
        "state": "reported", "value": value, "reason": reason,
        "checked_at": DATE, "locators": [{"url": url, "locator": locator}],
    }


EXTRA = (
    {
        "source_id": "S033",
        "extraction": {
            "target": field("At least 50% reduction of averaged NRS-now/NRS-average score after SCS implant", NATURE, "Methods, Patient reported outcome measures", "Primary Methods defines the responder calculation."),
            "follow_up": field("Postoperative patient-reported measures collected approximately three months after surgery", NATURE, "Methods, Patient reported outcome measures", "Within-patient follow-up is specified."),
            "patient_linkage": field("Preoperative PROMs and intraoperative EEG linked to postoperative NRS for 17 analyzed patients; leave-one-patient-out internal evaluation", NATURE, "Methods, Participants, Patient reported outcome measures and Machine learning; Results, Patient cohort", "Patient records connect predictors with later outcomes; no independent cohort."),
        },
    },
    {
        "source_id": "S749",
        "extraction": {
            "target": field("Global Health Improvement Score at least zero, computed from baseline-to-12-month VAS, ODI, MADRS and EQ-5D changes", OUNAJIM, "Methods 2.2.1 Primary Outcome and Table 2", "The primary composite is distinct from pain intensity alone."),
            "follow_up": field("Twelve-month SCS follow-up for ESTIMET and independent AIVOC cohorts", OUNAJIM, "Methods 2.1.1–2.1.2 and 2.2.1", "Both model development and external testing use the same horizon."),
            "patient_linkage": field("Baseline variables and 12-month outcomes linked for 91 ESTIMET patients and 12 independent AIVOC patients", OUNAJIM, "Methods 2.1.1–2.1.2, 2.3 and 2.5 External Validation", "Patients in the independent cohort were not used to train the model."),
        },
    },
    {
        "source_id": "S752",
        "extraction": {
            "target": field("At least 50% reduction of baseline visual analog pain score in the SCS subgroup", MEKHAIL, "Author abstract, Results", "The SCS denominator and target are explicit in the primary abstract."),
            "follow_up": field("Six months after permanent device implantation", MEKHAIL, "Author abstract, Materials and methods", "Baseline and six-month measures are specified."),
            "patient_linkage": field("Preimplant clinical predictors and baseline/six-month outcomes linked within 619 SCS recipients; previously developed single-center formula tested in independent multicenter registry", MEKHAIL, "Author abstract, Objective, Materials and methods, Results", "This is external validation across practices; 320 TDD recipients are a separate group."),
        },
    },
    {
        "source_id": "S753",
        "extraction": {
            "target": field("End-of-trial responder: at least 50% patient-reported pain relief, reported functional improvement, and willingness to receive permanent implant", POPE, "Methods, success criteria and Statistical Analysis; Results, Table 2", "The classification is based on patient reports and willingness; ECAP confirms/control activation."),
            "follow_up": field("End of temporary trial, mean 6.4 ± 1.5 days after Day-0 programming, range 3–12 days", POPE, "Results, first paragraph and Table 2", "This is a short trial horizon, not 12-month analgesia."),
            "patient_linkage": field("Paired Day-0 and end-of-trial assessments for the same 132 analyzed participants; no independent validation cohort", POPE, "Methods, Statistical Analysis; Results, 144 screened, 132 analyzed", "The 2x2 table links each participant's Day-0 and later trial status."),
        },
    },
    {
        "source_id": "S754",
        "extraction": {
            "target": field("One-year change in NRS, PGIC, ODI, BDI, MPQ and PCS; at least 50% NRS improvement or PROM-specific MCID for binary response", KABIR, "Author abstract, Materials and methods", "The author abstract defines the score families and response thresholds."),
            "follow_up": field("One year after SCS compared with preoperative baseline", KABIR, "Author abstract, Materials and methods", "The stated horizon is one year."),
            "patient_linkage": field("Preoperative clinical notes and PROMs paired with one-year outcomes for 20 SCS patients; train/test split and leakage controls unavailable in author abstract", KABIR, "Author abstract, Materials and methods and Conclusions", "Within-patient temporal pairing is explicit, while generalization remains unverified."),
        },
    },
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    payload = json.loads(AUDIT.read_text(encoding="utf-8"))
    existing = {entry["source_id"] for entry in payload["entries"]}
    if existing & {entry["source_id"] for entry in EXTRA}:
        raise ValueError("audit extension already applied")
    payload["entries"].extend(EXTRA)
    payload["entries"].sort(key=lambda entry: int(entry["source_id"][1:]))
    payload["meta"]["records_count"] = len(payload["entries"])
    payload["meta"]["remaining_source_ids"] = ["S034", "S046"]
    payload["meta"]["remaining_search_leads"] = [
        "Mekhail 2020 original formula", "De Jaeger 2021 high-dose multicenter model",
        "Sparkes 12-month FBSS model", "forward citation search for NS-11",
    ]
    if not args.apply:
        print(json.dumps({"would_add": [entry["source_id"] for entry in EXTRA], "records_count": len(payload["entries"])}, ensure_ascii=False))
        return 0
    snapshot = snapshot_repository(DATA, label="pre-ns11-audit-extension")
    atomic_write_json(AUDIT, payload)
    print(json.dumps({"snapshot": str(snapshot), "records_count": len(payload["entries"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
