"""Publish three backward-citation SCS outcome studies with source limits."""

# ruff: noqa: E501 -- primary titles, URLs and precise study boundaries are retained.

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json, publish_candidates

DATA = Path(__file__).resolve().parents[1] / "data"
INBOX = DATA / "staging" / "inbox" / "ns11-backward-analogues-2026-09-24.json"
DATE = "2026-09-24"
SOURCES = (
    {
        "id": "S755",
        "title": "Choice of spinal cord stimulation versus targeted drug delivery in the management of chronic pain: a predictive formula for outcomes",
        "authors": "Nagy Mekhail; Diana S. Mehanny; Sherif Armanyous; Shrif Costandi; Youssef Saweris; Gerges Azer; Robert Bolash",
        "year": 2020, "journal": "Regional Anesthesia & Pain Medicine",
        "doi": "10.1136/rapm-2019-100859", "pmid": "31932490",
        "url": "https://pubmed.ncbi.nlm.nih.gov/31932490/",
        "modality": "Retrospective clinical and demographic variables; no ECAP",
        "task": "Derive formula for SCS success versus subsequent targeted drug delivery after SCS failure",
        "method": "Retrospective univariate and multivariate analysis with a logistic SCS-success formula",
        "dataset": "945 Cleveland Clinic SCS-trial records from 1994–2013; 119 later achieved adequate relief with TDD after SCS failure",
        "performance": "Author abstract reports predictor directions but no held-out performance for the derived formula",
        "population": "Chronic nonmalignant pain patients undergoing SCS trial; TDD subgroup followed SCS failure",
        "sample_size": 945,
        "target_label": "SCS success versus failure and subsequent TDD relief; operational threshold and assessment horizon unavailable in accessible author abstract",
        "limitations": "The author abstract does not define the exact SCS-success threshold, outcome follow-up horizon, or patient-level split for model validation. This is derivation in one center, not the separate 2023 prospective external validation. No ECAP.",
        "status": "partially_verified", "full_text_status": "metadata_only", "access_status": "restricted",
        "external_validation": "no", "split_unit": "unavailable_after_search", "cross_subject": "unavailable_after_search",
        "risk_flags": ["metadata_only", "claim_not_supported"],
        "locators": {
            "датасет": "Author abstract, retrospective Cleveland Clinic 1994–2013 cohort and 945 records",
            "evidence.target_label": "Author abstract, SCS success versus TDD after failed SCS; threshold and horizon absent",
            "validation.notes": "Author abstract only; target threshold, follow-up and validation split unavailable",
        },
    },
    {
        "id": "S756",
        "title": "The Long-Term Response to High-Dose Spinal Cord Stimulation in Patients With Failed Back Surgery Syndrome After Conversion From Standard Spinal Cord Stimulation: An Effectiveness and Prediction Study",
        "authors": "Mats De Jaeger; Lisa Goudman; Raf Brouns; Ann De Smedt; Bengt Linderoth; Sam Eldabe; Discover consortium; Maarten Moens",
        "year": 2021, "journal": "Neuromodulation: Technology at the Neural Interface",
        "doi": "10.1111/ner.13138", "pmid": "32166849",
        "url": "https://pubmed.ncbi.nlm.nih.gov/32166849/",
        "modality": "Preconversion pain intensity, medication use, paresthesia coverage and EQ-5D; no ECAP",
        "task": "Predict 12-month response to high-dose SCS after unsatisfactory standard SCS",
        "method": "Longitudinal mixed models for effectiveness and logistic regression/decision trees for response predictors",
        "dataset": "78 failed-back-surgery-syndrome patients enrolled while receiving standard SCS, then converted to high-dose SCS",
        "performance": "Author abstract reports predictor variables but no independent validation metric",
        "population": "Failed-back-surgery-syndrome patients salvaged by conversion from standard to high-dose SCS",
        "sample_size": 78,
        "target_label": "At least 2/10 decrease in NRS after 12 months of high-dose SCS",
        "limitations": "Conversion/salvage cohort, not de novo SCS candidate selection. Accessible author abstract does not describe split construction, calibration or external validation; no ECAP.",
        "status": "partially_verified", "full_text_status": "metadata_only", "access_status": "restricted",
        "external_validation": "unavailable_after_search", "split_unit": "unavailable_after_search", "cross_subject": "unavailable_after_search",
        "risk_flags": ["metadata_only"],
        "locators": {
            "датасет": "Author abstract, Materials and methods, 78 patients receiving standard SCS before conversion",
            "evidence.target_label": "Author abstract, Materials and methods, NRS decrease at least 2/10 after 12 months",
            "validation.notes": "Author abstract, Methods and Results; split and external validation not described",
        },
    },
    {
        "id": "S757",
        "title": "Analysis of psychological characteristics impacting spinal cord stimulation treatment outcomes: a prospective assessment",
        "authors": "Elizabeth Sparkes; Rui V. Duarte; Stacey Mann; Tony R. Lawrence; Jon H. Raphael",
        "year": 2015, "journal": "Pain Physician",
        "doi": "10.36076/ppj.2015/18/E369", "pmid": "26000684",
        "url": "https://www.painphysicianjournal.com/current/pdf?article=MjMyOQ%3D%3D&journal=88",
        "modality": "Baseline psychological, coping and demographic measures; no ECAP",
        "task": "Associate baseline factors with 12-month SCS pain and disability improvement",
        "method": "Prospective longitudinal cohort and hierarchical regression; no held-out prognostic validation",
        "dataset": "75 recruited; 7 failed temporary trial, 12 lost within one year, 56 analyzed after implant",
        "performance": "Within-cohort 12-month VAS reduction regression adjusted R-squared 0.248; ODI improvement adjusted R-squared 0.336",
        "population": "Adults with chronic neuropathic pain receiving SCS after a successful trial",
        "sample_size": 56,
        "target_label": "Continuous baseline-to-12-month reduction in 100-mm VAS pain and improvement in ODI disability; no binary responder classifier",
        "limitations": "Selected implant cohort with 19/75 trial failures or follow-up losses; hierarchical regression reports in-sample associations, without participant-held-out or external prediction validation. Not specific to ECAP or high-dose SCS.",
        "status": "verified_primary", "full_text_status": "checked", "access_status": "open",
        "external_validation": "no", "split_unit": "not_applicable", "cross_subject": "no",
        "risk_flags": [],
        "locators": {
            "датасет": "Publisher PDF pp. E371–E372, Methods/Patients and Results; 75 to 56 flow",
            "производительность": "Publisher PDF pp. E373–E374, Tables 3–4, hierarchical regression",
            "evidence.target_label": "Publisher PDF p. E371, Sensory and psychological measures; Tables 3–4",
            "validation.external_validation": "Publisher PDF pp. E371–E374, same 56-person cohort in regression",
            "validation.notes": "Publisher PDF pp. E371–E374, no held-out prediction validation",
        },
    },
)


def candidates() -> list[dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))["sources"]
    base = next(record for record in records if record["id"] == "S749")
    output = []
    for spec in SOURCES:
        record = deepcopy(base)
        record.update({
            "id": spec["id"], "название": spec["title"], "авторы": spec["authors"],
            "год": spec["year"], "издание": spec["journal"],
            "модальность": spec["modality"], "задача": spec["task"], "метод": spec["method"],
            "датасет": spec["dataset"], "производительность": spec["performance"],
            "ограничения": spec["limitations"],
        })
        record["identifiers"] = {
            "doi": spec["doi"], "pmid": spec["pmid"], "arxiv_id": None,
            "patent_id": None, "dataset_id": None, "exact_url": spec["url"],
        }
        record["provenance"].update({
            "import_source": "PA-05 NS-11 backward citation review", "retrieved_at": DATE,
            "search_stream": "NS-11", "query_or_seed": spec["title"], "iteration": 4,
        })
        record["evidence"].update({
            "population": spec["population"], "sample_size": spec["sample_size"],
            "target_label": spec["target_label"], "access_status": spec["access_status"],
        })
        record["validation"].update({
            "status": spec["status"], "full_text_status": spec["full_text_status"],
            "split_unit": spec["split_unit"], "cross_subject": spec["cross_subject"],
            "external_validation": spec["external_validation"],
            "calibration": "not_reported", "uncertainty": "not_reported",
            "notes": spec["limitations"],
        })
        record["кросс_субъект"] = spec["cross_subject"]
        record["risk_flags"] = spec["risk_flags"]
        record = migrate_record(record, checked_at=DATE)
        for path, locator in spec["locators"].items():
            record["field_resolution"][path]["locators"] = [
                {"url": spec["url"], "locator": locator}
            ]
        output.append(record)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    atomic_write_json(INBOX, candidates())
    result = publish_candidates(DATA, INBOX, apply=args.apply)
    print(json.dumps({k: v for k, v in result.items() if k != "integrity"}, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
