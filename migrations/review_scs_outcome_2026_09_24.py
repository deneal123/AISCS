"""Separate ECAP measurements, other biomarkers, and SCS clinical outcomes."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from service.completeness import completeness_summary, migrate_record
from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
AUDIT = "scs-outcome-audit.json"

# Each value gives (state, value, exact primary-text locator).
SPECS: dict[str, dict[str, Any]] = {
    "S003": {
        "url": "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0337726",
        "notes": "MEG classification separates chronic-pain patients from pain-free controls and its scores correlate poorly with pain ratings in the SCS group (rho=0.12). There was no pre-implant baseline in the SCS group and no prospective SCS-responder classifier. MEG spectral features are not ECAP.",
        "evidence": {"target_construct": "self_reported_pain", "target_label": "Chronic-pain versus control class and concurrent NRS pain ratings", "evidence_role": "method_baseline"},
        "dimensions": {
            "input_role": ("reported", "Resting-state MEG spectral power and alpha/theta features; other neural signal, not ECAP", "Abstract, Methods, MEG spectral feature extraction"),
            "target_role": ("reported", "Chronic-pain/control classification and concurrent NRS pain ratings; not future SCS response", "Abstract Results and Conclusion; Discussion, absence of pre-implant baseline"),
            "study_design": ("reported", "25 SCS patients plus 25 chronic-pain patients and 25 pain-free controls; model evaluated with participant-held-out internal procedure", "Abstract and Methods, study population and machine learning"),
            "prognostic_validation": ("not_applicable", None, "Discussion: pre-implant baseline unavailable; no SCS-response prediction model or independent prognostic test"),
        },
    },
    "S033": {
        "url": "https://www.nature.com/articles/s41598-025-92111-8",
        "method": "Intraoperative EEG spectral features plus clinical features and preoperative PROMs; PCA/RFE feature selection, decision-tree model, leave-one-patient-out evaluation",
        "dataset": "20 SCS surgery patients recruited; 17 analyzed after excluding three without postoperative NRS; seven responders and ten nonresponders",
        "notes": "The model predicts at least 50% reduction in 3-month postoperative NRS, using intraoperative EEG, clinical variables and preoperative PROMs. Feature selection, hyperparameter/seed search and feature-count optimization are described before or across LOOCV, so the reported 88.2% accuracy and 0.879 AUROC may be optimistically biased. No independent external test and no ECAP input.",
        "evidence": {"species": "Homo sapiens", "population": "Adults undergoing SCS implant surgery for chronic back and/or leg pain", "subject_domain": "human_clinical", "modalities": ["eeg", "clinical_outcome"], "sample_size": 17, "target_construct": "scs_response", "target_label": "At least 50% reduction in average NRS pain within three months of surgery", "access_status": "open", "evidence_role": "method_baseline"},
        "validation": {"split_unit": "participant", "cross_subject": "yes", "external_validation": "no"},
        "dimensions": {
            "input_role": ("reported", "Intraoperative scalp EEG spectral features plus baseline clinical/PROM variables; no ECAP", "Abstract and Methods, Surgical procedure and neuro monitoring; Machine learning"),
            "target_role": ("reported", "Binary SCS responder: at least 50% reduction in NRS-average by approximately three months", "Methods, Patient cohort and outcome measures"),
            "study_design": ("reported", "20 recruited, 17 analyzed; leave-one-patient-out internal evaluation; feature selection before LOOCV and global tuning/feature-count search", "Methods, Machine learning; Results, Patient cohort and Fig. 5"),
            "prognostic_validation": ("reported", "Internal LOOCV only; no independent external cohort. 88.2% accuracy and 0.879 AUROC are subject to pre-LOOCV selection/tuning bias.", "Methods, Machine learning; Results, Table 3"),
        },
    },
    "S034": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/40879389/",
        "dimensions": {
            "input_role": ("reported", "Spinal imaging radiomics plus clinical variables; no ECAP named in accessible abstract", "Abstract, Methods"),
            "target_role": ("reported", "50% and 70% SCS responder targets", "Abstract, Results"),
            "study_design": ("unavailable_after_search", None, "PubMed abstract: cohort size, centers, split and feature-selection nesting absent; full text restricted"),
            "prognostic_validation": ("unavailable_after_search", None, "PubMed abstract: reports accuracy/AUROC, but not independent external validation or leakage controls"),
        },
    },
    "S046": {
        "url": "https://www.sciencedirect.com/science/article/abs/pii/S1094715925006439",
        "notes": "Conference abstract on 16 SCS recipients. Preoperative EEG alpha/theta/beta features, PCS helpfulness and other baseline data are candidate predictors of a three-month composite responder endpoint. The published abstract truncates the endpoint definition and gives no split construction or independent test; it is not ECAP-based.",
        "validation": {"external_validation": "not_reported"},
        "dimensions": {
            "input_role": ("reported", "Preoperative EEG, patient history and baseline pain measures; no ECAP", "Conference abstract, Methods and Results"),
            "target_role": ("reported", "Composite responder within three months; full three-component definition truncated in accessible abstract", "Conference abstract, Methods"),
            "study_design": ("reported", "16 patients and recursive feature elimination; split unit and nesting not reported", "Conference abstract, Methods and Results"),
            "prognostic_validation": ("not_reported", None, "Conference abstract: no described independent external test or split protocol"),
        },
    },
    "S105": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/40073452/",
        "dimensions": {
            "input_role": ("reported", "SCS-evoked ECAP signals recorded from epidural contacts", "Abstract and Methods, ECAP collection"),
            "target_role": ("reported", "ECAP waveform/features and neural recruitment, not clinical pain response", "Abstract and Results, ECAP feature extraction and prediction"),
            "study_design": ("reported", "Eight chronic-pain trial participants; repeated stimulation and contact measurements", "Methods, participants and stimulation protocol"),
            "prognostic_validation": ("not_applicable", None, "Methods and Results: no prospective clinical responder label or independent outcome prediction"),
        },
    },
    "S159": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/41605141/",
        "dimensions": {
            "input_role": ("reported", "SCS-evoked recordings contaminated by stimulation artifact", "Methods, recording and artifact model"),
            "target_role": ("reported", "Artifact-cleaning and ECAP signal quality, not patient pain response", "Abstract and Results, E-score"),
            "study_design": ("reported", "Two SCS patients and repeated signals across stimulation settings", "Methods, participants and recordings"),
            "prognostic_validation": ("not_applicable", None, "Results: no clinical outcome prediction endpoint"),
        },
    },
    "S236": {
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC12594148/",
        "dimensions": {
            "input_role": ("reported", "ECAP feedback controls SCS dosing; ECAP is a neural-recruitment signal", "Methods, closed-loop stimulation"),
            "target_role": ("reported", "12-month pain and multidomain clinical outcomes, separately measured from ECAP", "Results, clinical outcomes"),
            "study_design": ("reported", "68-patient subgroup of two prospective trials; no concurrent comparator for this analysis", "Methods and Discussion, subgroup analysis"),
            "prognostic_validation": ("not_applicable", None, "Methods and Results: treatment-outcome subgroup, no fitted prospective responder predictor"),
        },
    },
    "S239": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/39094810/",
        "dimensions": {
            "input_role": ("reported", "ECAP feedback adjusts stimulation dose", "Methods, ECHO-MAC trial intervention"),
            "target_role": ("reported", "Primary therapy-experience and dosing-stability measures; not pain-response prediction", "Abstract and Results, primary outcome"),
            "study_design": ("reported", "Randomized single-blind crossover trial, 42 participants in intent-to-treat analysis", "Methods and Results, participant flow"),
            "prognostic_validation": ("not_applicable", None, "Methods: intervention comparison rather than patient-level future responder model"),
        },
    },
    "S360": {
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13009343/",
        "dimensions": {
            "input_role": ("reported", "ECAP feedback therapy with a same-day trial", "Methods, ECAP-controlled SCS"),
            "target_role": ("reported", "Day-0 and later pain/multidomain response in selected responders", "Results, day-0 through 12-month outcomes"),
            "study_design": ("reported", "Single-center selected cohort: 15 day-0 responders, 13 implanted, 11 with complete 12-month follow-up", "Methods, selection; Results, follow-up"),
            "prognostic_validation": ("not_applicable", None, "Methods: all analyzed patients selected as day-0 responders; no independent unselected prediction cohort"),
        },
    },
    "S749": {
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC8538165/",
        "dimensions": {
            "input_role": ("reported", "Baseline clinical history and patient-reported measures; no ECAP or neural biomarker", "Methods, predictors and statistical models"),
            "target_role": ("reported", "12-month Global Health Improvement Score combining pain, disability, mood and quality of life", "Methods, composite outcome; Results, Table 2"),
            "study_design": ("reported", "ESTIMET 91-person development cohort with nested internal CV; AIVOC 12-person independent test", "Methods 2.3-2.5; Results, Table 1"),
            "prognostic_validation": ("reported", "External AIVOC n=12; RF AUROC 0.83 and RLR AUROC 0.81, with wide small-sample limits", "Methods 2.5; Results 3.3, Table 4"),
        },
    },
}


def _audit() -> dict[str, Any]:
    entries = []
    for source_id, spec in SPECS.items():
        extraction = {}
        for dimension, (state, value, locator) in spec["dimensions"].items():
            extraction[dimension] = {
                "state": state,
                "value": value,
                "reason": "Extracted from primary material." if state == "reported" else locator,
                "checked_at": DATE,
                "locators": [{"url": spec["url"], "locator": locator}],
            }
        entries.append({"source_id": source_id, "extraction": extraction})
    return {
        "meta": {"schema_version": "1.0.0", "generated_at": DATE, "records_count": len(entries), "gate": "G0_REVISE", "scope": "SCS clinical response prediction and explicit ECAP/technical/therapy-outcome contrasts"},
        "construct_boundary": "ECAP measures evoked neural recruitment; EEG, MEG and radiomics are other inputs; NRS and multidomain patient outcomes are clinical endpoints. Intervention outcomes are not automatically validated patient-level predictors.",
        "entries": entries,
    }


def build_outputs(data_dir: Path = DATA) -> dict[str, dict[str, Any]]:
    records = load_json(data_dir / "records.json")
    updated = []
    for original in records["sources"]:
        source_id = original["id"]
        if source_id not in SPECS:
            updated.append(original)
            continue
        spec = SPECS[source_id]
        record = deepcopy(original)
        changed = []
        for key, field in (("method", "метод"), ("dataset", "датасет"), ("notes", "ограничения")):
            if key in spec:
                record[field] = spec[key]
                changed.append(field)
        if "notes" in spec:
            record["validation"]["notes"] = spec["notes"]
            changed.append("validation.notes")
        for name, value in spec.get("evidence", {}).items():
            record["evidence"][name] = value
            changed.append("evidence." + name)
        for name, value in spec.get("validation", {}).items():
            record["validation"][name] = value
            changed.append("validation." + name)
        record["validation"]["checked_at"] = DATE
        record = migrate_record(record, checked_at=DATE)
        for path in changed:
            if path in record["field_resolution"]:
                record["field_resolution"][path]["locators"] = [{"url": spec["url"], "locator": "Primary full text or abstract, methods/results; " + path}]
        updated.append(record)
    records["sources"] = updated
    records["meta"]["updated_at"] = DATE
    by_id = {record["id"]: record for record in updated}
    clusters = load_json(data_dir / "clusters.json")
    for cluster in clusters["clusters"]:
        representative = cluster.get("представитель")
        if representative and representative.get("id") in SPECS:
            cluster["представитель"] = deepcopy(by_id[representative["id"]])
    clusters["meta"]["updated_at"] = DATE
    log = load_json(data_dir / "validation-log.json")
    log.setdefault("searches", []).append({"search_id": "SCS-OUTCOME-2026-09-24-01", "date": DATE, "stream": "SCS clinical outcome prediction and signal-role separation", "query": "exact titles and DOI at primary publishers, PubMed and PMC", "urls_reviewed": [spec["url"] for spec in SPECS.values()], "source_ids": sorted(SPECS), "decision": "ECAP, other predictors, clinical endpoints and independent validation distinguished"})
    log["meta"]["checked_at"] = DATE
    report = load_json(data_dir / "audit-report.json")
    report["meta"]["generated_at"] = DATE
    report["current_corpus"]["canonical_sources"] = len(updated)
    report["current_corpus"]["validation_statuses"] = dict(sorted(Counter(record["validation"]["status"] for record in updated).items()))
    report["scs_outcome_audit"] = {"checked_at": DATE, "source_ids": sorted(SPECS), "artifact": AUDIT, "finding": "No study's ECAP, EEG/MEG/radiomics and clinical outcome roles are conflated."}
    completeness = load_json(data_dir / "completeness-report.json")
    completeness.update(completeness_summary(updated))
    completeness["meta"]["generated_at"] = DATE
    return {"records.json": records, "clusters.json": clusters, "validation-log.json": log, "audit-report.json": report, "completeness-report.json": completeness, AUDIT: _audit()}


def validate_outputs(outputs: dict[str, dict[str, Any]], data_dir: Path = DATA) -> None:
    with tempfile.TemporaryDirectory(prefix="research-scs-outcome-") as temporary:
        target = Path(temporary)
        for path in data_dir.glob("*.json"):
            shutil.copy2(path, target / path.name)
        for name, payload in outputs.items():
            atomic_write_json(target / name, payload)
        result = validate_repository(target)
        if not result["ok"]:
            raise ValueError("; ".join(result["errors"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    outputs = build_outputs()
    validate_outputs(outputs)
    snapshot = None
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-scs-outcome-review")
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
        result = validate_repository(DATA)
        if not result["ok"]:
            raise RuntimeError(f"restore {snapshot}: {'; '.join(result['errors'])}")
    print(json.dumps({"ok": True, "applied": args.apply, "reviewed": sorted(SPECS), "snapshot": str(snapshot) if snapshot else None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
