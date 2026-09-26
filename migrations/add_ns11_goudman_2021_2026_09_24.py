"""Publish the Goudman 2021 Discover-registry prediction study as S762."""

# ruff: noqa: E501 -- precise abstract boundaries and source locators are retained.

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json, publish_candidates

DATA = Path(__file__).resolve().parents[1] / "data"
INBOX = DATA / "staging" / "inbox" / "ns11-goudman-2021-2026-09-24.json"
DATE = "2026-09-24"
PUBLISHER = "https://doi.org/10.1097/j.pain.0000000000002035"
PUBMED = "https://pubmed.ncbi.nlm.nih.gov/32910099/"


def candidates() -> list[dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))["sources"]
    base = next(record for record in records if record["id"] == "S756")
    record = deepcopy(base)
    record.update({
        "id": "S762",
        "название": "High-dose spinal cord stimulation for patients with failed back surgery syndrome: a multicenter effectiveness and prediction study",
        "авторы": "Lisa Goudman; Ann De Smedt; Sam Eldabe; Philippe Rigoard; Bengt Linderoth; Mats De Jaeger; Discover Consortium; Maarten Moens",
        "год": 2021,
        "издание": "Pain",
        "модальность": "Baseline clinical and patient-reported outcomes; no ECAP",
        "задача": "Predict 12-month holistic response to high-dose SCS in failed back surgery syndrome",
        "метод": "Multicenter Discover registry; longitudinal effectiveness analysis plus logistic regression and decision tree for holistic response",
        "датасет": "194 recruited; 185 baseline visits; 92 still receiving high-dose SCS at 12 months; model analysis denominator unavailable in abstract",
        "производительность": "Author abstract reports 90% sensitivity and specificity for holistic response, without a visible validation split or denominator",
        "кросс_субъект": "unavailable_after_search",
        "релевантность": 5,
        "ограничения": "Publisher abstract names four components of a 12-month holistic responder but omits their numeric thresholds, prediction analysis denominator and patient-disjoint split. The 90% sensitivity/specificity cannot be treated as external validation. Discover-registry cohorts in related studies may overlap; no ECAP.",
        "тип_источника": "применение",
    })
    record["identifiers"] = {
        "doi": "10.1097/j.pain.0000000000002035",
        "pmid": "32910099",
        "arxiv_id": None,
        "patent_id": None,
        "dataset_id": None,
        "exact_url": PUBMED,
    }
    record["provenance"] = {
        "import_source": "PA-05 NS-11 forward/backward search",
        "retrieved_at": DATE,
        "search_stream": "NS-11",
        "query_or_seed": "Goudman 2021 PMID 32910099",
        "iteration": 5,
    }
    record["evidence"].update({
        "species": "Homo sapiens",
        "population": "Adults with failed back surgery syndrome recruited to the multicenter Discover registry for high-dose SCS",
        "subject_domain": "human_clinical",
        "modalities": ["clinical_outcome", "other"],
        "sample_size": "194 recruited; 185 baseline; 92 receiving HD-SCS at 12 months",
        "target_construct": "scs_response",
        "target_label": "Twelve-month holistic responder combining pain intensity, medication use, ODI and EQ-5D changes; exact thresholds unavailable in abstract",
        "access_status": "restricted",
        "evidence_role": "method_baseline",
    })
    record["validation"].update({
        "status": "partially_verified",
        "screening_status": "included_core",
        "full_text_status": "metadata_only",
        "checked_at": DATE,
        "split_unit": "unavailable_after_search",
        "cross_subject": "unavailable_after_search",
        "external_validation": "unavailable_after_search",
        "calibration": "not_reported",
        "uncertainty": "not_reported",
        "exclusion_reason": None,
        "notes": "Primary publisher/PubMed abstracts establish recruitment, baseline-to-12-month assessments and composite domains, but not exact responder thresholds, predictor-analysis denominator or patient-disjoint training/test construction.",
    })
    record["relations"] = []
    record["risk_flags"] = ["metadata_only"]
    record = migrate_record(record, checked_at=DATE)
    locators = {
        "evidence.sample_size": "Author abstract: 194 recruited, 185 baseline visits, 92 continuing HD-SCS at 12 months",
        "evidence.target_label": "Author abstract: logistic regression/decision tree for holistic responder after 12 months; four domains listed without thresholds",
        "validation.notes": "Author abstract, Methods and Results; missing composite thresholds, analysis denominator and validation split",
        "validation.external_validation": "Author abstract does not describe independent cohort or held-out split",
        "производительность": "Author abstract, Results: sensitivity and specificity 90%, validation design unspecified",
    }
    for path, locator in locators.items():
        record["field_resolution"][path]["locators"] = [{"url": PUBLISHER, "locator": locator}]
    return [record]


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
