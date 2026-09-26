"""Record outcome-linkage evidence and open gaps from backward citations."""

# ruff: noqa: E501 -- primary locators and precise study statements are retained.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
AUDIT = DATA / "ns11-prediction-audit.json"
DATE = "2026-09-24"
MEKHAIL = "https://pubmed.ncbi.nlm.nih.gov/31932490/"
DE_JAEGER = "https://pubmed.ncbi.nlm.nih.gov/32166849/"
SPARKES = "https://www.painphysicianjournal.com/current/pdf?article=MjMyOQ%3D%3D&journal=88"


def reported(value: str, url: str, locator: str, reason: str) -> dict:
    return {"state": "reported", "value": value, "reason": reason, "checked_at": DATE,
            "locators": [{"url": url, "locator": locator}]}


def unavailable(url: str, locator: str, reason: str) -> dict:
    return {"state": "unavailable_after_search", "value": None, "reason": reason,
            "checked_at": DATE, "locators": [{"url": url, "locator": locator}]}


EXTRA = (
    {
        "source_id": "S755",
        "extraction": {
            "target": unavailable(MEKHAIL, "Author abstract, Results: SCS success described without an operational threshold", "Accessible primary abstract states SCS success but omits a numeric definition; BMJ full text was inaccessible in this pass."),
            "follow_up": unavailable(MEKHAIL, "Author abstract, Methods: retrospective 1994–2013 records; no outcome visit window", "The primary abstract does not specify elapsed time from SCS trial or implant to outcome determination."),
            "patient_linkage": unavailable(MEKHAIL, "Author abstract, Methods: 945 SCS-trial records, 119 later TDD successes", "Cohort and treatment sequence are described, but exact linkage/analysis set for the formula and split construction are not specified in the accessible primary text."),
        },
    },
    {
        "source_id": "S756",
        "extraction": {
            "target": reported("At least 2/10 decrease in NRS for low back or leg pain after conversion from standard to high-dose SCS", DE_JAEGER, "Author abstract, Materials and methods", "Responder definition is explicit in the primary abstract."),
            "follow_up": reported("One, three and twelve months after high-dose SCS conversion; prediction target at twelve months", DE_JAEGER, "Author abstract, Materials and methods", "The prediction endpoint is the twelve-month visit."),
            "patient_linkage": reported("Preconversion clinical variables and repeated outcomes belong to the 78 enrolled FBSS patients; exact twelve-month retention and validation split are not given in abstract", DE_JAEGER, "Author abstract, Materials and methods and Results", "Longitudinal cohort design supports within-patient linkage but not an independent test claim."),
        },
    },
    {
        "source_id": "S757",
        "extraction": {
            "target": reported("Continuous reduction in 100-mm VAS pain and improvement in ODI disability from baseline; hierarchical regression, no binary responder classifier", SPARKES, "Publisher PDF pp. E371–E374, Measures and Tables 3–4", "The paper analyzes continuous within-person outcomes."),
            "follow_up": reported("Baseline before SCS trial, then six and twelve months after implantation; predictor analyses target twelve months", SPARKES, "Publisher PDF pp. E371–E374, Methods and Tables 3–4", "The analysis horizon is specified in the primary full text."),
            "patient_linkage": reported("Same 56 implant recipients measured at baseline, six and twelve months; 75 recruited, seven failed trial and twelve lost to follow-up; no held-out test", SPARKES, "Publisher PDF pp. E371–E374, participant flow, Table 1 and regression Methods", "Paired outcomes are analyzed in one selected cohort, without external prognostic validation."),
        },
    },
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    payload = json.loads(AUDIT.read_text(encoding="utf-8"))
    seen = {entry["source_id"] for entry in payload["entries"]}
    if seen & {entry["source_id"] for entry in EXTRA}:
        raise ValueError("backward-citation audit entries already present")
    payload["entries"].extend(EXTRA)
    payload["entries"].sort(key=lambda entry: int(entry["source_id"][1:]))
    payload["meta"]["records_count"] = len(payload["entries"])
    payload["meta"]["remaining_source_ids"] = ["S034", "S046", "S755"]
    payload["meta"]["remaining_search_leads"] = [
        "Goudman 2021 multicenter high-dose model",
        "S034 and S046 full text or author manuscripts",
        "Mekhail 2020 full text for operational outcome and horizon",
        "forward citation search for NS-11",
    ]
    if not args.apply:
        print(json.dumps({"would_add": [entry["source_id"] for entry in EXTRA], "records_count": len(payload["entries"])}, ensure_ascii=False))
        return 0
    snapshot = snapshot_repository(DATA, label="pre-ns11-backward-audit")
    atomic_write_json(AUDIT, payload)
    print(json.dumps({"snapshot": str(snapshot), "records_count": len(payload["entries"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
