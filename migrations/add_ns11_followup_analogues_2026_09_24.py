"""Stage three distinct SCS outcome-prediction analogues for PA-05."""

# ruff: noqa: E501 -- exact article titles, primary URLs and locators are intentionally retained.

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json, publish_candidates

DATA = Path(__file__).resolve().parents[1] / "data"
INBOX = DATA / "staging" / "inbox" / "ns11-followup-analogues-2026-09-24.json"
DATE = "2026-09-24"
SOURCES = (
    {
        "id": "S752",
        "title": "The Choice of Spinal Cord Stimulation Versus Targeted Drug Delivery in the Management of Chronic Pain: Validation of an Outcomes Predictive Formula",
        "authors": "Nagy Mekhail; Sherif Armanyous; Erin Templeton; Nicholas Prayson; Youssef Saweris",
        "year": 2023,
        "journal": "Neuromodulation: Technology at the Neural Interface",
        "doi": "10.1016/j.neurom.2023.02.083",
        "pmid": "37061895",
        "url": "https://pubmed.ncbi.nlm.nih.gov/37061895/",
        "modality": "Preimplant demographic, clinical and pain-diagnosis variables; no ECAP",
        "task": "Externally validate a previously developed clinical formula for 6-month SCS response",
        "method": "Logistic prediction formula developed at one center, prospectively tested in a multicenter product-surveillance registry",
        "dataset": "939 enrolled after successful SCS or targeted-drug-delivery trials; 619 SCS recipients and 320 TDD recipients",
        "performance": "In the SCS validation subgroup, 138/619 met the target; reported AUROC 0.80",
        "population": "Adults with chronic pain after successful SCS trial in a multicenter US registry",
        "sample_size": 619,
        "target_label": "At least 50% reduction in baseline visual analog pain score at 6 months after implant",
        "limitations": "Author abstract establishes external practice-level validation and patient-linked baseline/6-month values, but full text and calibration details were not available in this pass. The 939 total includes 320 targeted-drug-delivery recipients who must not be counted as SCS cases. No ECAP.",
        "status": "partially_verified",
        "full_text_status": "metadata_only",
        "access_status": "restricted",
        "external_validation": "yes",
        "split_unit": "participant",
        "cross_subject": "yes",
        "risk_flags": ["metadata_only"],
        "locators": {
            "датасет": "Author abstract, Materials and methods; SCS/TDD denominators in Results",
            "производительность": "Author abstract, Results, 619 SCS recipients and AUROC 0.80",
            "evidence.target_label": "Author abstract, Materials and methods and Results, VAS baseline to six months",
            "validation.external_validation": "Author abstract, Objective and Materials and methods, prior single-center formula tested in independent practices",
            "validation.notes": "Author abstract only; full model and calibration details unavailable in this pass",
        },
    },
    {
        "id": "S753",
        "title": "Identifying SCS Trial Responders Immediately After Postoperative Programming with ECAP Dose-Controlled Closed-Loop Therapy",
        "authors": "Jason E. Pope; Ajay Antony; Erika A. Petersen; Steven M. Rosen; Dawood Sayed; Corey W. Hunter; Johnathan H. Goree; Chau M. Vu; Harjot S. Bhandal; Philip M. Shumsky; Todd A. Bromberg; G. Lawson Smith; Christopher M. Lam; Hemant Kalia; Jennifer M. Lee; Abeer Khurram; Ian Gould; Dean M. Karantonis; Timothy R. Deer",
        "year": 2024,
        "journal": "Pain and Therapy",
        "doi": "10.1007/s40122-024-00631-4",
        "pmid": "38977651",
        "url": "https://link.springer.com/article/10.1007/s40122-024-00631-4",
        "modality": "Day-0 patient-reported pain relief, function and willingness; ECAP confirms/control neural activation but is not the responder label",
        "task": "Predict end-of-trial SCS response from same-day postprogramming assessment",
        "method": "Prospectively collected paired Day-0/end-of-trial evaluations; 2x2 contingency analysis, not a long-term ML predictor",
        "dataset": "132 analyzed ECAP dose-controlled closed-loop SCS trial patients after exclusions",
        "performance": "Day-0 success PPV 60/61 (98.4%) for end-of-trial success; sensitivity 60/114 (52.6%)",
        "population": "Adults undergoing temporary ECAP-controlled closed-loop SCS trial",
        "sample_size": 132,
        "target_label": "End-of-trial success: at least 50% patient-reported pain relief plus functional improvement and willingness to implant",
        "limitations": "Predicts end-of-trial status after an average 6.4-day trial, not 12-month analgesia. Day-0 ECAP dose measures did not separate success groups; the predictive classification uses patient reports and willingness. PPV reflects an 86.4% trial-success prevalence.",
        "status": "verified_primary",
        "full_text_status": "checked",
        "access_status": "open",
        "external_validation": "no",
        "split_unit": "participant",
        "cross_subject": "yes",
        "risk_flags": [],
        "locators": {
            "датасет": "Methods, Statistical Analysis; Results, 144 assessed and 132 analyzed",
            "производительность": "Results, Table 2, 60/61 PPV and 60/114 sensitivity",
            "evidence.target_label": "Methods, Success criteria and Statistical Analysis",
            "validation.external_validation": "Methods, paired Day-0 and end-of-trial comparison in one cohort",
            "validation.notes": "Abstract and Results, Day-0 ECAP measures not different; Discussion, short-horizon limitation",
        },
    },
    {
        "id": "S754",
        "title": "Proof of Concept of Natural Language Processing in Predicting Patient-Reported Outcomes in Spinal Cord Stimulation",
        "authors": "Mahir Kabir; Theresa Medina; Sohail Rajesh Daulat; Marisa DiMarzio; Julie G. Pilitsis",
        "year": 2026,
        "journal": "Neuromodulation: Technology at the Neural Interface",
        "doi": "10.1016/j.neurom.2026.06.464",
        "pmid": "42524811",
        "url": "https://pubmed.ncbi.nlm.nih.gov/42524811/",
        "modality": "Clinical notes represented with TF-IDF, BERT-base or Bio-ClinicalBERT; predictor text timing is unclear in the abstract; no ECAP",
        "task": "Predict postoperative patient-reported improvement after SCS",
        "method": "Proof-of-concept NLP models with rank correlations and binary MCID/responder assessments; split details unavailable in abstract",
        "dataset": "20 SCS patients with preoperative and one-year postoperative notes and PROMs",
        "performance": "TF-IDF rank correlation with NRS improvement rho -0.76; authors state individual responder identification remains elusive",
        "population": "20 patients receiving SCS with paired clinical notes and patient-reported measures",
        "sample_size": 20,
        "target_label": "One-year improvement in NRS, PGIC, ODI, BDI, MPQ and PCS; NRS responder at least 50% improvement, other PROMs by MCID",
        "limitations": "Small proof-of-concept cohort (n=20); accessible author abstract mentions preoperative and one-year postoperative clinical notes but does not specify which text entered prediction, leakage controls, train/test split or independent validation. Its within-dataset rank correlations do not establish individual responder prediction. No ECAP.",
        "status": "partially_verified",
        "full_text_status": "metadata_only",
        "access_status": "restricted",
        "external_validation": "unavailable_after_search",
        "split_unit": "unavailable_after_search",
        "cross_subject": "unavailable_after_search",
        "risk_flags": ["metadata_only", "claim_not_supported"],
        "locators": {
            "датасет": "Author abstract, Materials and methods, 20 paired preoperative/one-year patients",
            "производительность": "Author abstract, Results and Conclusions, correlations and responder caveat",
            "evidence.target_label": "Author abstract, Materials and methods, NRS and MCID outcomes",
            "validation.external_validation": "Author abstract, no split or independent cohort specified",
            "validation.notes": "Author abstract, Conclusions, individual responder identification elusive",
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
            "модальность": spec["modality"], "задача": spec["task"],
            "метод": spec["method"], "датасет": spec["dataset"],
            "производительность": spec["performance"], "ограничения": spec["limitations"],
        })
        record["identifiers"] = {
            "doi": spec["doi"], "pmid": spec["pmid"], "arxiv_id": None,
            "patent_id": None, "dataset_id": None, "exact_url": spec["url"],
        }
        record["provenance"].update({
            "import_source": "PA-05 NS-11 primary-source review", "retrieved_at": DATE,
            "search_stream": "NS-11", "query_or_seed": spec["title"], "iteration": 3,
        })
        record["evidence"].update({
            "population": spec["population"], "sample_size": spec["sample_size"],
            "target_label": spec["target_label"], "access_status": spec["access_status"],
        })
        if spec["id"] == "S753":
            record["evidence"]["modalities"] = ["ecap", "clinical_outcome"]
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
