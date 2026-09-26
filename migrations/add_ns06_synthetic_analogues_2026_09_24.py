"""Publish two primary synthetic facial-pain analogues for NS-06."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json, new_candidate, publish_candidates

DATA = Path(__file__).resolve().parents[1] / "data"
INBOX = DATA / "staging" / "inbox" / "ns06-synthetic-analogues-2026-09-24.json"
DATE = "2026-09-24"


def candidate(source_id: str, spec: dict) -> dict:
    record = new_candidate(DATA, spec["title"])
    record["id"] = source_id
    record.update(spec["legacy"])
    record["identifiers"].update(
        {"arxiv_id": spec["arxiv_id"], "exact_url": spec["url"]}
    )
    record["provenance"].update(
        {
            "import_source": "NS-06 primary full-text and citation search",
            "retrieved_at": DATE,
            "search_stream": "NS-06 synthetic pain/domain adaptation",
            "query_or_seed": spec["title"],
            "iteration": 2,
        }
    )
    record["evidence"].update(spec["evidence"])
    record["validation"].update(spec["validation"])
    record["risk_flags"] = ["future_or_recent_record_requires_recheck"]
    record = migrate_record(record, checked_at=DATE)
    for path, item in record["field_resolution"].items():
        item["locators"] = [
            {
                "url": spec["url"],
                "locator": spec["locators"].get(path, spec["default_locator"]),
            }
        ]
    return record


SYNPAIN = {
    "title": "Syn Pain: A Synthetic Dataset of Pain and Non-Pain Facial Expressions",
    "arxiv_id": "2507.19673",
    "url": "https://arxiv.org/html/2507.19673",
    "default_locator": "v3, abstract and Sections III and VI; field-specific value or absence",
    "legacy": {
        "авторы": "Babak Taati; Muhammad Muzammil; Yasamin Zarghami; Abhishek Moturu; Amirhossein Kazerouni; Hailey Reimer; Alex Mihailidis; Thomas Hadjistavropoulos",
        "год": 2025,
        "издание": "arXiv:2507.19673v3 (2026 revision of 2025 preprint)",
        "модальность": "Synthetic paired neutral and expressive facial images; real facial images for augmentation test",
        "задача": "Synthetic facial-expression dataset, demographic-bias audit and real-data augmentation",
        "метод": "Prompted synthetic identities and pain/non-pain expressions; age-matched augmentation of PwCT",
        "датасет": "10,710 synthetic images from 5,355 identity pairs; UNBC-McMaster and UofR real images; UofR fivefold evaluation on 95 older adults",
        "производительность": "UofR overall average precision 0.345 real-only versus 0.369 with age-matched synthetic augmentation; AUROC 0.775 versus 0.778",
        "кросс_субъект": "Fivefold UofR cross-validation; identity unit of real folds is not explicitly stated in Section VI",
        "релевантность": 5,
        "ограничения": "A visual-only dataset and augmentation study with labeled UNBC and UofR real training data. UofR contributes training and test folds, so this is not a fully independent external cohort or synthetic-source unlabeled-target adaptation. Synthetic facial pain expression and PSPI are observable proxies, not subjective pain reports.",
        "тип_источника": "генеративные_модели",
    },
    "evidence": {
        "species": "Homo sapiens and synthetic human faces",
        "population": "Synthetic young and older adult identities; 95 real older adults in UofR evaluation",
        "subject_domain": "mixed",
        "modalities": ["video_face"],
        "sample_size": "5,355 synthetic identity pairs; 95 UofR participants",
        "target_construct": "experimental_pain_class",
        "target_label": "Facial pain/non-pain expression and PSPI-derived detection",
        "access_status": "open",
        "evidence_role": "method_baseline",
    },
    "validation": {
        "status": "verified_primary",
        "screening_status": "included_core",
        "full_text_status": "checked",
        "checked_at": DATE,
        "split_unit": "not_reported",
        "cross_subject": "not_reported",
        "external_validation": "no",
        "calibration": "not_reported",
        "uncertainty": "not_reported",
        "notes": "Version 3 reports 2.4 percentage points of AP improvement, replacing an older 7.0% figure. Section VI uses labeled UNBC and UofR training folds. The UofR fold unit is not explicit in that section; no separate external cohort is tested.",
    },
    "locators": {
        "датасет": "v3, Abstract, Section III Syn Pain Dataset, and Section VI External Evaluation",
        "производительность": "v3, Section VI, Tables XIV-XV",
        "validation.split_unit": "v3, Section VI: fivefold UofR cross-validation; no explicit fold unit",
        "validation.external_validation": "v3, Section VI: UofR used in training and evaluation folds",
    },
}


THREEDPAIN = {
    "title": "Pain in 3D: Controllable Generation of Synthetic Faces for Automated Pain Assessment",
    "arxiv_id": "2509.16727",
    "url": "https://arxiv.org/html/2509.16727",
    "default_locator": "v5, abstract and Sections 3-5; field-specific value or absence",
    "legacy": {
        "авторы": "Xin Lei Lin; Soroush Mehraban; Abhishek Moturu; Babak Taati",
        "год": 2025,
        "издание": "arXiv:2509.16727v5 (2026 revision of 2025 preprint)",
        "модальность": "Synthetic 3D facial images and real facial frames",
        "задача": "AU-controlled synthetic facial pain generation and visual PSPI estimation",
        "метод": "FLAME mesh, diffusion texture and AU rigging; ViTPain with neutral-reference cross-attention",
        "датасет": "3DPain 82,500 frames across 2,500 synthetic identities; UNBC-McMaster 48,398 real frames from 25 participants",
        "производительность": "UNBC fivefold subject-independent evaluation: ViTPain with 3DPain pretraining AUROC 0.86 at PSPI>=1 and 0.89 at PSPI>=3",
        "кросс_субъект": "Yes; fivefold subject-independent UNBC evaluation",
        "релевантность": 5,
        "ограничения": "Visual PSPI task with UNBC real evaluation and cross-validation; no independent second real dataset. The text calls UNBC reserved for evaluation but also describes fivefold cross-validation and fine-tuning, so real-label use in training folds requires clarification. No physiological synthetic modality or unlabeled-target domain alignment as in S149.",
        "тип_источника": "генеративные_модели",
    },
    "evidence": {
        "species": "Homo sapiens and synthetic human faces",
        "population": "Synthetic adult identities and 25 real UNBC participants",
        "subject_domain": "mixed",
        "modalities": ["video_face"],
        "sample_size": "2,500 synthetic identities; 25 UNBC participants",
        "target_construct": "experimental_pain_class",
        "target_label": "Facial Action Units and PSPI 0-16",
        "access_status": "open",
        "evidence_role": "method_baseline",
    },
    "validation": {
        "status": "verified_primary",
        "screening_status": "included_core",
        "full_text_status": "checked",
        "checked_at": DATE,
        "split_unit": "participant",
        "cross_subject": "yes",
        "external_validation": "no",
        "calibration": "not_reported",
        "uncertainty": "not_reported",
        "notes": "Version 5 reports a 70/20/10 identity-disjoint synthetic split and fivefold subject-independent UNBC evaluation. Whether real UNBC labels enter training folds is internally ambiguous between the cross-validation/fine-tuning description and the phrase 'reserved strictly for evaluation'. No independent second real cohort is reported.",
    },
    "locators": {
        "датасет": "v5, Abstract, Section 3 and Section 5 Datasets and Class Imbalance",
        "производительность": "v5, Section 5, Table 2 and Performance Comparison",
        "validation.split_unit": "v5, Section 5, paragraph after Table 4: subject-independent fivefold UNBC splits",
        "validation.external_validation": "v5, Section 5: UNBC only real evaluation dataset",
        "validation.notes": "v5, Section 5 Implementation Details versus Ablation Studies",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    first = new_candidate(DATA, SYNPAIN["title"])["id"]
    number = int(first[1:])
    records = [candidate(first, SYNPAIN), candidate(f"S{number + 1:03d}", THREEDPAIN)]
    atomic_write_json(INBOX, records)
    result = publish_candidates(DATA, INBOX, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
