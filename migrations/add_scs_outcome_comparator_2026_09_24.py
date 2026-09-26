"""Build the reviewed 2021 clinical SCS outcome-prediction comparator."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json, new_candidate, publish_candidates

DATA = Path(__file__).resolve().parents[1] / "data"
INBOX = DATA / "staging" / "inbox" / "scs-outcome-comparator-2026-09-24.json"
DATE = "2026-09-24"
URL = "https://pmc.ncbi.nlm.nih.gov/articles/PMC8538165/"
TITLE = (
    "Machine Learning Algorithms Provide Greater Prediction of Response to SCS "
    "Than Lead Screening Trial: A Predictive AI-Based Multicenter Study"
)


def candidate() -> dict:
    record = new_candidate(DATA, TITLE)
    if record["id"] != "S749":
        raise ValueError(f"expected S749, got {record['id']}")
    record.update(
        {
            "авторы": (
                "Amine Ounajim; Maxime Billot; Lisa Goudman; Pierre-Yves Louis; "
                "Yousri Slaoui; Manuel Roulaud; Bénédicte Bouche; Philippe Page; "
                "Bertille Lorgeoux; Sandrine Baron; Nihel Adjali; Kevin Nivole; "
                "Nicolas Naiditch; Chantal Wood; Raphaël Rigoard; Romain David; "
                "Maarten Moens; Philippe Rigoard"
            ),
            "год": 2021,
            "издание": "Journal of Clinical Medicine",
            "модальность": "Baseline demographics, clinical history and patient-reported outcomes",
            "задача": "Prediction of 12-month composite clinical SCS response before implantation",
            "метод": "Logistic and regularized regression, SVM, naive Bayes, ANN, CART, random forest and gradient boosting; nested internal CV and an independent test cohort",
            "датасет": "ESTIMET 91 training patients; AIVOC 12 independent testing patients; persistent spinal pain syndrome after surgery",
            "производительность": "External AIVOC cohort (n=12): RLR AUROC 0.81, RF AUROC 0.83; comparison with lead screening trial AUROC 0.69",
            "кросс_субъект": "yes",
            "релевантность": 5,
            "ограничения": "Independent cohort is only 12 patients, with six good and six bad composite outcomes. Predictors are baseline clinical variables and patient reports; no ECAP or other neural biomarker is measured. The outcome combines pain, disability, mood and quality of life, so it is not a direct pain-intensity estimator.",
            "тип_источника": "применение",
        }
    )
    record["identifiers"].update(
        {"doi": "10.3390/jcm10204764", "pmid": "34682887", "exact_url": URL}
    )
    record["provenance"].update(
        {
            "import_source": "SRC-06 primary comparator review",
            "retrieved_at": DATE,
            "search_stream": "scs-outcome-prediction",
            "query_or_seed": TITLE,
            "iteration": 1,
        }
    )
    record["evidence"].update(
        {
            "species": "Homo sapiens",
            "population": "Adults with persistent spinal pain syndrome after spine surgery considered for SCS",
            "subject_domain": "human_clinical",
            "modalities": ["clinical_outcome", "other"],
            "sample_size": 103,
            "target_construct": "scs_response",
            "target_label": "12-month Global Health Improvement Score combining VAS, ODI, MADRS and EQ-5D",
            "access_status": "open",
            "evidence_role": "method_baseline",
        }
    )
    record["validation"].update(
        {
            "status": "verified_primary",
            "screening_status": "included_core",
            "full_text_status": "checked",
            "checked_at": DATE,
            "split_unit": "participant",
            "cross_subject": "yes",
            "external_validation": "yes",
            "calibration": "not_reported",
            "uncertainty": "yes",
            "notes": record["ограничения"],
        }
    )
    record["risk_flags"] = []
    record = migrate_record(record, checked_at=DATE)
    for path, locator in {
        "датасет": "Methods, ESTIMET training n=91 and AIVOC independent testing n=12",
        "производительность": "Results, Table 4 external validation",
        "evidence.target_label": "Methods, composite Global Health Improvement Score",
        "validation.external_validation": "Methods 2.5 External Validation; Results 3.3 and Table 4",
        "validation.notes": "Methods 2.4-2.5 and Results 3.3; absence of ECAP in predictor list",
    }.items():
        record["field_resolution"][path]["locators"] = [{"url": URL, "locator": locator}]
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    atomic_write_json(INBOX, candidate())
    result = publish_candidates(DATA, INBOX, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
