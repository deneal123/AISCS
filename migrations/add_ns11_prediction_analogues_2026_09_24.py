"""Publish two primary full-text SCS response-prediction analogues."""

# ruff: noqa: E501 -- retain exact titles, primary URLs and audit locators.

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json, publish_candidates

DATA = Path(__file__).resolve().parents[1] / "data"
INBOX = DATA / "staging" / "inbox" / "ns11-prediction-analogues-2026-09-24.json"
DATE = "2026-09-24"
SOURCES = (
    {
        "id": "S750",
        "title": "Predicting the Response of High Frequency Spinal Cord Stimulation in Patients with Failed Back Surgery Syndrome: A Retrospective Study with Machine Learning Techniques",
        "authors": "Lisa Goudman; Jean-Pierre Van Buyten; Ann De Smedt; Iris Smet; Marieke Devos; Ali Jerjir; Maarten Moens",
        "year": 2020,
        "journal": "Journal of Clinical Medicine",
        "doi": "10.3390/jcm9124131",
        "pmid": "33371497",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC7767526/",
        "modality": "Baseline clinical variables and SCS trial pain relief; no ECAP",
        "task": "Predict HF-10 SCS clinical response at last available follow-up",
        "method": "Logistic regression, LDA, trees, random forest, bagging and boosting; one random participant-level 80/20 split",
        "dataset": "119 patients with failed back surgery syndrome; 95 training and 24 validation patients",
        "performance": "Validation accuracy: 58.33% for at least 50% pain relief; 70.83% for at least 30% relief",
        "limitations": "Retrospective last-visit outcome has variable follow-up (median 591.5 days, IQR 312.5–815.8); one internal split, no independent external cohort. Trial pain relief is a post-trial predictor, not a pre-implant baseline variable. No ECAP.",
        "sample_size": 119,
        "target_label": "At last visit versus baseline: at least 50% or 30% pain relief in predominant pain location; separate at least 41.2% medication-use reduction",
        "external_validation": "no",
        "locators": {
            "датасет": "Methods 2.2 and Results 3.1, 119 patients; Results 3.1, 95/24 split",
            "производительность": "Abstract and Results 3.3, Table 2",
            "evidence.target_label": "Methods 2.3, three responder definitions",
            "validation.external_validation": "Methods 2.4 and Results 3.1, one internal 80/20 split",
            "validation.notes": "Results 3.1, median last follow-up 591.5 days; Discussion, variable follow-up",
        },
    },
    {
        "id": "S751",
        "title": "Development of Machine Learning–Based Models to Predict Treatment Response to Spinal Cord Stimulation",
        "authors": "Amir Hadanny; Tessa Harland; Olga Khazen; Marisa DiMarzio; Anthony Marchese; Ilknur Telkes; Vishad Sukul; Julie G. Pilitsis",
        "year": 2022,
        "journal": "Neurosurgery",
        "doi": "10.1227/neu.0000000000001855",
        "pmid": "35179133",
        "url": "https://telkeslab.com/wp-content/uploads/2023/05/Hadanny-Telkes_2022_Development-of-Machine-Learning%E2%80%93Based-Models-to-Predict-Treatment-Response-to-Spinal-Cord-Stimulation.pdf",
        "modality": "Preoperative demographics, diagnoses and patient-reported outcomes; no ECAP",
        "task": "Predict 1-year patient-reported NRS response after permanent SCS placement",
        "method": "K-means phenotype clusters and logistic regression, random forest and XGBoost; nested 10-fold participant-level cross-validation",
        "dataset": "151 included patients from 261 baseline records; permanent SCS implant and 10–14-month follow-up required",
        "performance": "Internal nested-CV logistic regression AUROC 0.757 and 0.708 for two clusters with ten selected features",
        "limitations": "Single-center selected follow-up cohort; 108 baseline records excluded, including 100 outside the 10–14-month visit window. Internal nested CV only; authors call for prospective external validation. No ECAP.",
        "sample_size": 151,
        "target_label": "More than 50% NRS reduction at 10–14 months; high responder more than 70% reduction",
        "external_validation": "no",
        "locators": {
            "датасет": "PDF p. 2, Methods/Patients and Fig. 1, 151 included from 261 baseline records",
            "производительность": "PDF p. 1 Abstract and p. 6 Table 4",
            "evidence.target_label": "PDF p. 2, Methods/Patients, pre-SCS and 1-year NRS linked within patients",
            "validation.external_validation": "PDF p. 2, Methods/Models, nested 10-fold CV; p. 8 Limitations, external validation needed",
            "validation.notes": "PDF p. 2, Methods/Patients, 10–14 months and exclusions; p. 8 Limitations",
        },
    },
)


def candidates() -> list[dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))["sources"]
    base = next(record for record in records if record["id"] == "S749")
    result = []
    for spec in SOURCES:
        record = deepcopy(base)
        record.update(
            {
                "id": spec["id"],
                "название": spec["title"],
                "авторы": spec["authors"],
                "год": spec["year"],
                "издание": spec["journal"],
                "модальность": spec["modality"],
                "задача": spec["task"],
                "метод": spec["method"],
                "датасет": spec["dataset"],
                "производительность": spec["performance"],
                "ограничения": spec["limitations"],
            }
        )
        record["identifiers"] = {
            "doi": spec["doi"], "pmid": spec["pmid"], "arxiv_id": None,
            "patent_id": None, "dataset_id": None, "exact_url": spec["url"],
        }
        record["provenance"].update(
            {"import_source": "PA-05 NS-11 primary full-text review", "retrieved_at": DATE,
             "search_stream": "NS-11", "query_or_seed": spec["title"], "iteration": 2}
        )
        record["evidence"].update(
            {"population": "Adults treated with spinal cord stimulation for chronic pain",
             "sample_size": spec["sample_size"], "target_label": spec["target_label"]}
        )
        record["validation"].update(
            {"external_validation": spec["external_validation"], "uncertainty": "not_reported",
             "notes": spec["limitations"]}
        )
        record = migrate_record(record, checked_at=DATE)
        for path, locator in spec["locators"].items():
            record["field_resolution"][path]["locators"] = [
                {"url": spec["url"], "locator": locator}
            ]
        result.append(record)
    return result


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
