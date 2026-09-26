"""Upgrade four priority metadata-only records from checked primary full texts."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from service.completeness import completeness_summary, migrate_record
from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-24"

UPDATES: dict[str, dict[str, Any]] = {
    "S003": {
        "url": "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0337726",
        "модальность": "Resting-state MEG spectral features from 94 atlas regions",
        "задача": "Chronic-pain classification and exploratory association with concurrent SCS-session outcomes",
        "метод": "WORC ensemble with leave-one-participant-out evaluation and nested 5x random-split model selection",
        "датасет": "25 SCS patients, 25 chronic-pain patients, and 25 pain-free controls; SCS group measured after tonic, burst, and sham weeks",
        "производительность": "Chronic-pain versus control accuracy 76%; theta AUC 0.80; SCS-group classifier score versus NRS Spearman rho 0.12",
        "кросс_субъект": "yes: leave-one-participant-out cross-validation",
        "ограничения": "Small single-study cohorts; no pre-implant baseline and no independent external dataset. The chronic-pain classifier output correlated poorly with SCS-group pain ratings and is not a validated SCS-response predictor.",
        "evidence": {
            "species": "Homo sapiens",
            "population": "Adults with implanted SCS, adults with chronic pain, and pain-free controls",
            "subject_domain": "human_clinical",
            "modalities": ["meg", "clinical_outcome"],
            "sample_size": 75,
            "target_construct": "scs_response",
            "target_label": "NRS pain score and chronic-pain/control group",
            "access_status": "open",
            "evidence_role": "scs_ecap_validation",
        },
        "validation": {
            "split_unit": "participant",
            "cross_subject": "yes",
            "external_validation": "no",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
        },
        "risk_flags": ["ecap_not_pain_measure"],
        "locator": "Experimental setup; Results, Table 1-3 and Fig. 2; Discussion, Limitations",
        "claim": "MEG features separated chronic-pain patients from controls, but the transferred classifier score did not validate SCS pain response.",
        "permitted": "Use as a negative/limiting precedent for SCS-outcome transfer; do not describe it as ECAP evidence or successful response prediction.",
    },
    "S015": {
        "url": "https://www.mdpi.com/1424-8220/26/10/3020",
        "pmid": "42197829",
        "модальность": "Electrodermal activity at 100 Hz",
        "задача": "Three-class experimentally induced pain-intensity recognition and real-time deployment",
        "метод": "Fully convolutional network with strict subject-wise five-fold cross-validation",
        "датасет": "AI4Pain: 65 healthy participants; independent real-time GUI cohort of 15 unseen participants",
        "производительность": "79.23% offline accuracy; 73.14% real-time accuracy; 0.47 ms FCN inference latency",
        "кросс_субъект": "yes: subject-wise five-fold split; independent 15-participant real-time cohort",
        "ограничения": "Controlled TENS-evoked experimental pain in healthy participants; EDA reflects autonomic response and does not establish chronic-pain, ECAP, or SCS-outcome validity.",
        "evidence": {
            "species": "Homo sapiens",
            "population": "65 healthy participants plus 15 unseen healthy participants",
            "subject_domain": "human_healthy",
            "modalities": ["eda"],
            "sample_size": 80,
            "target_construct": "experimental_pain_class",
            "target_label": "No Pain, Low Pain, High Pain",
            "access_status": "open",
            "evidence_role": "human_validation",
        },
        "validation": {
            "split_unit": "participant",
            "cross_subject": "yes",
            "external_validation": "yes",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
        },
        "risk_flags": [],
        "locator": "Methods 2.1, 2.2, 2.3.3, 2.3.4; Results; Tables 1, 5, 7 and 8",
        "claim": "Subject-wise evaluation and an unseen-participant deployment cohort support EDA classification of controlled experimental pain classes.",
        "permitted": "Use as a human experimental-pain and real-time baseline, not as evidence for chronic pain, ECAP, or SCS outcomes.",
    },
    "S037": {
        "url": "https://www.nature.com/articles/s41598-025-14238-y",
        "модальность": "EDA and ECG; EDA and BVP in the cross-dataset check",
        "задача": "Multimodal experimental pain-class recognition",
        "метод": "FCN-ALSTM with intra-modal and inter-modal CrossMod-Transformer fusion",
        "датасет": "BioVid Part A, 87 participants; AI4Pain hold-out cross-dataset evaluation",
        "производительность": "BioVid accuracy 85.92% in subject-stratified 10-fold CV and 87.52% in LOSO; AI4Pain multimodal accuracy 75.83%",
        "кросс_субъект": "yes: subject-stratified ten-fold and leave-one-subject-out evaluation",
        "ограничения": "BioVid uses extreme heat-pain classes and AI4Pain uses a different cardiac modality and hold-out scheme. Cross-dataset use is not evidence for chronic pain, ECAP, or SCS outcomes.",
        "evidence": {
            "species": "Homo sapiens",
            "population": "Healthy participants exposed to controlled experimental pain",
            "subject_domain": "human_healthy",
            "modalities": ["eda", "ecg", "bvp_ppg"],
            "sample_size": 87,
            "target_construct": "experimental_pain_class",
            "target_label": "BioVid no-pain versus very-severe-pain; AI4Pain three classes",
            "access_status": "open",
            "evidence_role": "method_baseline",
        },
        "validation": {
            "split_unit": "participant",
            "cross_subject": "yes",
            "external_validation": "yes",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
        },
        "risk_flags": [],
        "locator": "Experimental setup; Results, Tables 5-7; Data availability",
        "claim": "Multimodal fusion was evaluated with subject-wise BioVid splits and a separate AI4Pain cross-dataset hold-out.",
        "permitted": "Use as a multimodal experimental-pain baseline; keep dataset and target-construct differences explicit.",
    },
    "S069": {
        "url": "https://journals.plos.org/plosbiology/article?id=10.1371/journal.pbio.3003948",
        "модальность": "64-channel EEG and trial-wise verbal pain ratings",
        "задача": "Repeatability and cross-cohort replicability of within- and between-person neural encoding of experimental pain",
        "метод": "Bayesian multivariate multi-model regression with repeated session and independent cohort",
        "датасет": "161 healthy participants measured twice about four weeks apart; independent cohort n=111",
        "производительность": "Between-person patterns repeated across sessions but failed cross-cohort replication; within-person patterns were robust across time and cohort",
        "кросс_субъект": "yes: independent-cohort replication explicitly tested",
        "ограничения": "Brief laser-evoked experimental pain in healthy participants; results warn against assuming stable between-person neural pain markers and do not validate chronic-pain or SCS transfer.",
        "evidence": {
            "species": "Homo sapiens",
            "population": "Healthy adults receiving brief painful laser stimuli",
            "subject_domain": "human_healthy",
            "modalities": ["eeg"],
            "sample_size": 272,
            "target_construct": "self_reported_pain",
            "target_label": "verbal numerical pain rating 0-100",
            "access_status": "open",
            "evidence_role": "human_validation",
        },
        "validation": {
            "split_unit": "participant",
            "cross_subject": "yes",
            "external_validation": "yes",
            "calibration": "not_reported",
            "uncertainty": "yes",
        },
        "risk_flags": [],
        "locator": "Abstract; Study overview; Results, Robustness and Fig. 6; Data availability",
        "claim": "Within-person EEG-pain associations replicated, whereas between-person patterns did not replicate across cohorts.",
        "permitted": "Use to require independent participant-level validation and to reject untested cross-person generalization.",
    },
    "S236": {
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC12594148/",
        "pmid": "40590186",
        "модальность": "ECAP device telemetry and patient-reported clinical outcomes",
        "задача": "Twelve-month outcomes and neural-dose metrics for ECAP-controlled closed-loop SCS",
        "метод": "Subgroup analysis of two prospective multicenter clinical trials",
        "датасет": "68 patients with chronic nonsurgical refractory back pain",
        "производительность": "At 12 months, 79% reported at least 50% pain reduction and 48% at least 80%; utilization exceeded 80% and ECAP target error was within 3.5 microvolts",
        "кросс_субъект": "not_applicable: clinical cohort analysis, not a predictive model",
        "ограничения": "Single-treatment subgroup analysis without a concurrent comparator for this question. ECAP metrics quantify neural recruitment and dosing; they are not a direct pain measurement or prospective response predictor.",
        "evidence": {
            "species": "Homo sapiens",
            "population": "Adults with chronic nonsurgical refractory back pain receiving SCS",
            "subject_domain": "human_clinical",
            "modalities": ["ecap", "clinical_outcome"],
            "sample_size": 68,
            "target_construct": "scs_response",
            "target_label": "12-month pain reduction and multidomain clinical outcomes",
            "access_status": "open",
            "evidence_role": "scs_ecap_validation",
        },
        "validation": {
            "split_unit": "participant",
            "cross_subject": "not_applicable",
            "external_validation": "no",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
        },
        "risk_flags": ["ecap_not_pain_measure"],
        "locator": "Abstract, Materials and Methods, Results; 12-month outcomes and device metrics",
        "claim": "Prospective cohorts link ECAP-controlled dose delivery with 12-month clinical outcomes in an NSRBP subgroup.",
        "permitted": "Use as clinical closed-loop SCS evidence while keeping ECAP dose accuracy distinct from pain measurement and prediction.",
    },
    "S237": {
        "url": "https://rapm.bmj.com/content/early/2025/12/01/rapm-2025-107051",
        "pmid": "41330601",
        "модальность": "ECAP device telemetry, VAS, PROMIS-29, and clinical outcomes",
        "задача": "Real-world clinical utility and neural-dose characterization of ECAP-controlled SCS",
        "метод": "Prospective multicenter single-arm pragmatic observational study at 22 US sites",
        "датасет": "231 implanted patients; 220 with required outcome and device data",
        "производительность": "Dose ratio at maximal analgesic effect was about 1.3 with 2.8 microvolt neural-dose accuracy; clinical improvements were maintained post-implant across diagnosis subgroups",
        "кросс_субъект": "not_applicable: observational clinical cohort, not a predictive model",
        "ограничения": "Single-arm observational design cannot isolate causal contribution of ECAP dosing from treatment and selection effects. ECAP is a recruitment/dose signal, not a direct pain measure.",
        "evidence": {
            "species": "Homo sapiens",
            "population": "Adults with chronic intractable trunk or limb pain receiving EVOKE SCS",
            "subject_domain": "human_clinical",
            "modalities": ["ecap", "clinical_outcome"],
            "sample_size": 220,
            "target_construct": "scs_response",
            "target_label": "VAS and multidomain minimal clinically important differences",
            "access_status": "open",
            "evidence_role": "scs_ecap_validation",
        },
        "validation": {
            "split_unit": "participant",
            "cross_subject": "not_applicable",
            "external_validation": "no",
            "calibration": "not_reported",
            "uncertainty": "yes",
        },
        "risk_flags": ["ecap_not_pain_measure"],
        "locator": "Methods, Study design and population; Results; Discussion; supplemental Table 1",
        "claim": "A 22-site pragmatic cohort reports ECAP neural-dose metrics alongside patient-reported outcomes across chronic-pain diagnoses.",
        "permitted": "Use as real-world ECAP dosing evidence, not as proof that ECAP directly measures pain or predicts individual response.",
    },
}


def _resolution(record: dict[str, Any], path: str, locator: str) -> None:
    item = record["field_resolution"][path]
    item["reason"] = "Value extracted from the checked publisher full text."
    item["checked_at"] = DATE
    item["locators"] = [{"url": record["identifiers"]["exact_url"], "locator": locator}]


def _upgrade(record: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    updated = dict(record)
    for field in (
        "модальность",
        "задача",
        "метод",
        "датасет",
        "производительность",
        "кросс_субъект",
        "ограничения",
    ):
        updated[field] = spec[field]
    updated["identifiers"] = dict(record["identifiers"])
    updated["identifiers"]["exact_url"] = spec["url"]
    if spec.get("pmid"):
        updated["identifiers"]["pmid"] = spec["pmid"]
    updated["evidence"] = dict(spec["evidence"])
    updated["validation"] = {
        **record["validation"],
        **spec["validation"],
        "status": "verified_primary",
        "full_text_status": "checked",
        "checked_at": DATE,
        "notes": spec["ограничения"],
    }
    updated["risk_flags"] = spec["risk_flags"]
    updated = migrate_record(updated, checked_at=DATE)
    for path in updated["field_resolution"]:
        _resolution(updated, path, spec["locator"])
    return updated


def build_outputs(data_dir: Path = DATA) -> dict[str, dict[str, Any]]:
    records = load_json(data_dir / "records.json")
    found: set[str] = set()
    upgraded: list[dict[str, Any]] = []
    for record in records["sources"]:
        if record["id"] in UPDATES:
            record = _upgrade(record, UPDATES[record["id"]])
            found.add(record["id"])
        upgraded.append(record)
    if found != set(UPDATES):
        raise ValueError(f"missing source IDs: {sorted(set(UPDATES) - found)}")
    records["sources"] = upgraded
    records["meta"].update(
        {
            "records_count": len(upgraded),
            "verified_primary_count": sum(
                item["validation"]["status"] == "verified_primary" for item in upgraded
            ),
            "updated_at": DATE,
        }
    )

    evidence = load_json(data_dir / "evidence-matrix.json")
    for row in evidence["rows"]:
        source_ids = row.get("source_ids", [])
        if len(source_ids) == 1 and source_ids[0] in UPDATES:
            source_id = source_ids[0]
            spec = UPDATES[source_id]
            row.update(
                {
                    "batch_id": "priority-full-text-2026-09-24",
                    "claim": spec["claim"],
                    "target_variable": spec["evidence"]["target_label"],
                    "population_or_data": spec["evidence"]["population"],
                    "verified_evidence": spec["производительность"],
                    "limitations": spec["ограничения"],
                    "permitted_conclusion": spec["permitted"],
                    "locators": [
                        {
                            "source_id": source_id,
                            "url": spec["url"],
                            "locator": spec["locator"],
                        }
                    ],
                }
            )
    evidence["meta"]["generated_at"] = DATE

    audit = load_json(data_dir / "audit-report.json")
    statuses = Counter(item["validation"]["status"] for item in upgraded)
    audit["current_corpus"].update(
        {
            "canonical_sources": len(upgraded),
            "validation_statuses": dict(sorted(statuses.items())),
        }
    )
    audit["meta"]["generated_at"] = DATE
    audit["priority_full_text_refresh"] = {
        "checked_at": DATE,
        "upgraded_source_ids": sorted(UPDATES),
        "scope": "publisher full-text extraction for priority human validation records",
    }

    validation_log = load_json(data_dir / "validation-log.json")
    searches = validation_log.setdefault("searches", [])
    searches[:] = [item for item in searches if item.get("search_id") != "FULLTEXT-2026-09-24-01"]
    searches.append(
        {
            "search_id": "FULLTEXT-2026-09-24-01",
            "date": DATE,
            "stream": "priority human datasets and SCS transfer limitations",
            "query": "exact title and DOI followed by publisher full text",
            "urls_reviewed": [UPDATES[key]["url"] for key in sorted(UPDATES)],
            "source_ids": sorted(UPDATES),
            "decision": "upgraded_to_verified_primary",
        }
    )
    validation_log["meta"]["checked_at"] = DATE

    completeness = load_json(data_dir / "completeness-report.json")
    completeness.update(completeness_summary(upgraded))
    completeness["meta"]["generated_at"] = DATE
    return {
        "records.json": records,
        "evidence-matrix.json": evidence,
        "audit-report.json": audit,
        "validation-log.json": validation_log,
        "completeness-report.json": completeness,
    }


def validate_outputs(outputs: dict[str, dict[str, Any]], data_dir: Path = DATA) -> None:
    with tempfile.TemporaryDirectory(prefix="research-fulltext-") as temporary:
        target = Path(temporary)
        for path in data_dir.glob("*.json"):
            shutil.copy2(path, target / path.name)
        for name, payload in outputs.items():
            atomic_write_json(target / name, payload)
        report = validate_repository(target)
        if not report["ok"]:
            raise ValueError("; ".join(report["errors"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    outputs = build_outputs()
    validate_outputs(outputs)
    snapshot = None
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-priority-full-text-refresh")
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
    print(
        json.dumps(
            {
                "ok": True,
                "applied": args.apply,
                "upgraded": sorted(UPDATES),
                "snapshot": str(snapshot) if snapshot else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
