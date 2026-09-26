"""Review relevance-4 neuromodulation and pain-device patent records."""

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

from migrations.review_ecap_scs_batch_2026_09_24 import (
    CROSS_SUBJECT,
    DATASET,
    LIMITATIONS,
    METHOD,
    MODALITY,
    PERFORMANCE,
    TASK,
    _update_record,
)
from service.completeness import completeness_summary
from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-24"
BATCH_ID = "neuromodulation-patent-review-2026-09-24"

UPDATES: dict[str, dict[str, Any]] = {
    "S098": {
        "url": "https://patents.google.com/patent/US11666761B2/en",
        "fields": {
            MODALITY: "Subjective pain reports, wearable physiological indicators and programmable SCS waveforms",
            TASK: "Machine-learning search for a patient-specific neuromodulation parameter set",
            METHOD: "Genetic algorithm or neural network searches spatial and temporal waveform parameters using a patient metric",
            DATASET: None,
            PERFORMANCE: None,
            CROSS_SUBJECT: "not_reported: patent embodiments, not an empirical evaluation",
            LIMITATIONS: "Granted patent claims and embodiments are prior art, not evidence that the optimization improves pain or clinical outcomes. No cohort, dataset, split, metric, calibration or independent validation is disclosed. The claimed 'objective pain metric' is a physiological indication and is not established as subjective pain.",
        },
        "evidence": {
            "species": "Homo sapiens or preclinical animals in claimed embodiments",
            "population": "No empirical cohort reported",
            "subject_domain": "mixed",
            "modalities": ["clinical_outcome", "other"],
            "sample_size": None,
            "target_construct": "scs_response",
            "target_label": "Candidate SCS parameter set selected from subjective or physiological patient metrics",
            "access_status": "open",
            "evidence_role": "context_only",
        },
        "validation": {
            "status": "verified_primary",
            "full_text_status": "checked",
            "split_unit": "not_reported",
            "cross_subject": "not_reported",
            "external_validation": "not_reported",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
        },
        "risk_flags": ["patent_not_empirical_evidence", "claim_not_supported"],
        "locator": "US11666761B2, bibliographic record; Examples 1-35; Figures 7-11; independent claims",
        "claim": "The patent claims ML-guided search of spatial and temporal SCS waveform parameters using subjective or physiological patient metrics.",
        "verified": "Publication identity, assignee, priority family, ML optimization mechanism and claimed inputs were checked in the patent text.",
        "permitted": "Use as parameter-optimization prior art only; do not cite it as evidence of pain measurement, clinical benefit or generalization.",
    },
    "S099": {
        "url": "https://patents.justia.com/patent/12642969",
        "fields": {
            MODALITY: "ECAP signals, stimulation parameters and optional external movement or physiological sensors",
            TASK: "Adjust stimulation therapy after spinal-cord injury using ECAP characteristics",
            METHOD: "Closed-loop comparison of ECAP amplitude, width, phase, slope, area or delay with target/template values, optionally combined with ML and external sensors",
            DATASET: None,
            PERFORMANCE: None,
            CROSS_SUBJECT: "not_reported: patent claims, not an empirical evaluation",
            LIMITATIONS: "Patent claims address spinal-cord-injury functions such as standing, locomotion and bladder control, not analgesic response. No patient cohort, outcome data, split or performance is disclosed. ECAP is used as neural feedback and is not a direct pain measure.",
        },
        "evidence": {
            "species": "Homo sapiens in claimed embodiments",
            "population": "Patients with prior spinal-cord damage; no empirical cohort reported",
            "subject_domain": "human_clinical",
            "modalities": ["ecap", "clinical_outcome", "movement_pose"],
            "sample_size": None,
            "target_construct": "clinical_function",
            "target_label": "SCI-related motor, autonomic or other functional response controlled using ECAP feedback",
            "access_status": "open",
            "evidence_role": "context_only",
        },
        "validation": {
            "status": "verified_primary",
            "full_text_status": "checked",
            "split_unit": "not_reported",
            "cross_subject": "not_reported",
            "external_validation": "not_reported",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
        },
        "risk_flags": ["patent_not_empirical_evidence", "ecap_not_pain_measure", "claim_not_supported"],
        "locator": "US12642969B2 patent text mirror, description of ECAP feedback and claims 1-12",
        "claim": "The granted patent claims iterative ECAP-guided adjustment of stimulation for functions impaired by spinal-cord injury.",
        "verified": "The full patent text and claims confirm ECAP features, target/template control, optional ML and functional rather than analgesic endpoints.",
        "permitted": "Use as ECAP closed-loop functional-neuromodulation prior art; do not treat it as pain or SCS analgesic-outcome evidence.",
    },
    "S144": {
        "url": "https://eureka.patsnap.com/patent/WO2026146221A1",
        "fields": {
            MODALITY: "Neurostimulator, neural-sensing and brain-computer-interface data distributed across sites and users",
            TASK: "Predict evolution of neural-interface characteristics and generate personalized operating or usage adjustments",
            METHOD: "Federated or multi-site machine-learning model parameters combined into predictive neural-interface models deployable to cloud or edge devices",
            DATASET: None,
            PERFORMANCE: None,
            CROSS_SUBJECT: "not_reported: patent disclosure without empirical validation",
            LIMITATIONS: "The WIPO identifier and extensive disclosure were located in a patent index, but the official WIPO full-text page was not accessible through the reproducible query. The disclosure is patent prior art and reports no cohort, public data, split, metrics or clinical outcomes.",
        },
        "evidence": {
            "species": "Homo sapiens in claimed neural-interface applications",
            "population": "Multiple neural-interface devices or users across sites; no empirical cohort reported",
            "subject_domain": "human_clinical",
            "modalities": ["neural_activity", "clinical_outcome", "other"],
            "sample_size": None,
            "target_construct": "clinical_function",
            "target_label": "Predicted evolution of a neurostimulation or neural-sensing characteristic",
            "access_status": "restricted",
            "evidence_role": "context_only",
        },
        "validation": {
            "status": "partially_verified",
            "full_text_status": "metadata_only",
            "split_unit": "not_reported",
            "cross_subject": "not_reported",
            "external_validation": "not_reported",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
        },
        "risk_flags": ["patent_not_empirical_evidence", "metadata_only", "claim_not_supported"],
        "locator": "WO2026146221A1 indexed disclosure, paragraphs 0004-0022 and 0046-0047; official WIPO page unavailable",
        "claim": "A 2026 patent disclosure describes federated multi-site predictive models for adaptive neurostimulation and neural interfaces.",
        "verified": "Publication number, publication date, assignee and the indexed federated-learning/predictive-adjustment mechanism were confirmed; official claims were not checked.",
        "permitted": "Use as partially verified adaptive-neural-interface prior art; do not attribute claim scope, performance or clinical effectiveness beyond the indexed disclosure.",
    },
    "S240": {
        "url": "https://patents.google.com/patent/US20230123383A1/en",
        "fields": {
            MODALITY: "EEG localization, ECAP, ECG, movement, respiration and other multidimensional patient features",
            TASK: "Closed-loop or clinician-assisted neurostimulation programming from a multidimensional patient state",
            METHOD: "Feature extraction and projection relative to patient/healthy-population representations, system identification and AI/ML decision models",
            DATASET: None,
            PERFORMANCE: None,
            CROSS_SUBJECT: "not_reported: population representations are claimed, but no empirical split is disclosed",
            LIMITATIONS: "Patent embodiments mention population models, ECAP and automatic parameter adjustment but disclose no evaluable cohort, dataset, metric, calibration or clinical outcome. Distance toward a healthy-control feature center is a claimed control objective, not a validated pain or treatment-response endpoint.",
        },
        "evidence": {
            "species": "Homo sapiens in claimed embodiments",
            "population": "Patients and healthy-control populations in claimed feature models; no empirical cohort reported",
            "subject_domain": "human_clinical",
            "modalities": ["eeg", "ecap", "ecg", "movement_pose", "clinical_outcome", "other"],
            "sample_size": None,
            "target_construct": "clinical_function",
            "target_label": "Patient-state feature distance used to adjust neurostimulation parameters",
            "access_status": "open",
            "evidence_role": "context_only",
        },
        "validation": {
            "status": "verified_primary",
            "full_text_status": "checked",
            "split_unit": "not_reported",
            "cross_subject": "not_reported",
            "external_validation": "not_reported",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
        },
        "risk_flags": ["patent_not_empirical_evidence", "ecap_not_pain_measure", "claim_not_supported"],
        "locator": "US20230123383A1, Abstract; Figures 28-39; multidimensional analysis description; claims 1-20",
        "claim": "The patent application claims population-relative multidimensional physiological models for closed-loop neurostimulation programming.",
        "verified": "The full disclosure confirms EEG/physiology inputs, optional ECAP processing, population feature spaces and automatic stimulation-parameter adjustment.",
        "permitted": "Use as multidimensional closed-loop programming prior art, not as empirical proof of cross-subject generalization or pain relief.",
    },
    "S241": {
        "url": "https://patents.google.com/patent/US20250099764A1/en",
        "fields": {
            MODALITY: "Applied SCS waveforms, sensed electrode energy and ECAP components",
            TASK: "Recover and identify an applied neuromodulation waveform after estimating and subtracting ECAP",
            METHOD: "Calibration of a body/electrode communication-channel impulse response, deconvolution or adaptive equalization, ECAP estimation and waveform-library matching",
            DATASET: None,
            PERFORMANCE: None,
            CROSS_SUBJECT: "not_reported: patent embodiments, not an empirical evaluation",
            LIMITATIONS: "The patent supplies a concrete observation-channel and signal-separation analogue, but no cohort, waveform dataset, error metric or validation is reported. Its primary task is waveform identification/licensing and protocol conformance, not pain estimation or ECAP-based efficacy prediction.",
        },
        "evidence": {
            "species": "Homo sapiens in claimed embodiments",
            "population": "SCS patients in claimed embodiments; no empirical cohort reported",
            "subject_domain": "human_clinical",
            "modalities": ["ecap", "other"],
            "sample_size": None,
            "target_construct": "technical_signal_quality",
            "target_label": "Applied waveform identity after channel correction and ECAP subtraction",
            "access_status": "open",
            "evidence_role": "context_only",
        },
        "validation": {
            "status": "verified_primary",
            "full_text_status": "checked",
            "split_unit": "not_reported",
            "cross_subject": "not_reported",
            "external_validation": "not_reported",
            "calibration": "yes",
            "uncertainty": "not_reported",
        },
        "risk_flags": ["patent_not_empirical_evidence", "ecap_not_pain_measure", "claim_not_supported"],
        "locator": "US20250099764A1, Abstract; channel-estimation and ECAP-isolation description; claims 1-15",
        "claim": "The patent application explicitly models the body/electrode path as a communication channel and separates ECAP from the applied waveform before matching.",
        "verified": "The patent text confirms calibration signals, channel impulse response, deconvolution/adaptive equalization, ECAP estimation and subtraction.",
        "permitted": "Use as prior art for an explicit ECAP measurement/observation operator; do not claim empirical accuracy or pain/SCS outcome prediction.",
    },
    "S245": {
        "url": "https://patents.google.com/patent/CN120478838B/en",
        "fields": {
            MODALITY: "EMG, skin conductance, body-surface temperature, heart rate and cerebral oxygenation",
            TASK: "Wearable pain-state estimation controlling transcutaneous electrical stimulation and remote monitoring",
            METHOD: "Weighted multimodal fusion followed by PID plus differential compensation for stimulation-intensity control",
            DATASET: None,
            PERFORMANCE: None,
            CROSS_SUBJECT: "not_reported: patent claims, not an empirical evaluation",
            LIMITATIONS: "The granted Chinese patent claims a device architecture but provides no cohort, label definition, training data, split, metric, calibration or clinical validation. The generated pain estimate is a controller input, not a demonstrated measure of subjective pain, and the stimulation is transcutaneous rather than SCS.",
        },
        "evidence": {
            "species": "Homo sapiens in claimed embodiments",
            "population": "Postoperative or chronic-neuropathic-pain use scenarios; no empirical cohort reported",
            "subject_domain": "human_clinical",
            "modalities": ["emg", "eda", "bvp_ppg", "fnirs", "other"],
            "sample_size": None,
            "target_construct": "clinical_function",
            "target_label": "Multimodal pain estimate used to control transcutaneous stimulation",
            "access_status": "open",
            "evidence_role": "context_only",
        },
        "validation": {
            "status": "verified_primary",
            "full_text_status": "checked",
            "split_unit": "not_reported",
            "cross_subject": "not_reported",
            "external_validation": "not_reported",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
        },
        "risk_flags": ["patent_not_empirical_evidence", "claim_not_supported"],
        "locator": "CN120478838B, translated Abstract and claims 1-3",
        "claim": "The patent claims a wearable multimodal pain estimate in a PID-controlled transcutaneous-stimulation loop.",
        "verified": "The translated patent abstract and claims confirm sensor types, weighted fusion, controller and remote-monitoring architecture.",
        "permitted": "Use as non-SCS multimodal closed-loop device prior art; do not cite it as a validated pain estimator or clinical treatment result.",
    },
    "S272": {
        "url": "https://patents.google.com/patent/CN122075919A/en",
        "fields": {
            MODALITY: None,
            TASK: None,
            METHOD: None,
            DATASET: None,
            PERFORMANCE: None,
            CROSS_SUBJECT: None,
            LIMITATIONS: "The exact publication identifier was searched in Google Patents, general web indexes and patent-topic indexes on 2026-09-24. No primary full text, reliable title, inventors, assignee, abstract or claims were recoverable. The record remains identity-only and cannot support any scientific or prior-art mechanism claim.",
        },
        "evidence": {
            "species": None,
            "population": None,
            "subject_domain": "unavailable_after_search",
            "modalities": [],
            "sample_size": None,
            "target_construct": "unavailable_after_search",
            "target_label": None,
            "access_status": "unavailable_after_search",
            "evidence_role": "context_only",
        },
        "validation": {
            "status": "verified_metadata",
            "full_text_status": "unavailable",
            "split_unit": "unavailable_after_search",
            "cross_subject": "unavailable_after_search",
            "external_validation": "unavailable_after_search",
            "calibration": "unavailable_after_search",
            "uncertainty": "unavailable_after_search",
        },
        "risk_flags": ["patent_not_empirical_evidence", "metadata_only", "claim_not_supported"],
        "locator": "Exact identifier searches for CN122075919A; Google Patents returned no document and no official full text was located",
        "claim": "A bibliographic candidate with identifier CN122075919A was recorded, but its content could not be verified.",
        "verified": "Only the candidate publication identifier was retained; no substantive patent content was verified.",
        "permitted": "Do not use this record for any scientific, technical or novelty claim unless an official patent text is recovered.",
    },
}


def build_outputs(data_dir: Path = DATA) -> dict[str, dict[str, Any]]:
    records = load_json(data_dir / "records.json")
    found: set[str] = set()
    sources: list[dict[str, Any]] = []
    for record in records["sources"]:
        if record["id"] in UPDATES:
            record = _update_record(record, UPDATES[record["id"]])
            found.add(record["id"])
        sources.append(record)
    if found != set(UPDATES):
        raise ValueError(f"missing source IDs: {sorted(set(UPDATES) - found)}")
    records["sources"] = sources
    statuses = Counter(source["validation"]["status"] for source in sources)
    records["meta"].update({"verified_primary_count": statuses["verified_primary"], "updated_at": DATE})
    by_id = {source["id"]: source for source in sources}

    evidence = load_json(data_dir / "evidence-matrix.json")
    single_rows = {row["source_ids"][0]: row for row in evidence["rows"] if len(row.get("source_ids", [])) == 1}
    for source_id, spec in UPDATES.items():
        source = by_id[source_id]
        payload = {
            "batch_id": BATCH_ID,
            "claim": spec["claim"],
            "target_variable": source["evidence"]["target_label"] or "unavailable after documented search",
            "population_or_data": source["evidence"]["population"] or "unavailable after documented search",
            "source_ids": [source_id],
            "verified_evidence": spec["verified"],
            "limitations": source[LIMITATIONS],
            "permitted_conclusion": spec["permitted"],
            "locators": [{"source_id": source_id, "url": spec["url"], "locator": spec["locator"]}],
        }
        if source_id in single_rows:
            single_rows[source_id].update(payload)
        else:
            evidence["rows"].append(payload)
    evidence["meta"]["generated_at"] = DATE

    clusters = load_json(data_dir / "clusters.json")
    for cluster in clusters["clusters"]:
        representative = cluster.get("представитель")
        if representative and representative.get("id") in UPDATES:
            cluster["представитель"] = deepcopy(by_id[representative["id"]])
        if any(source_id in UPDATES for source_id in cluster.get("состав_кластера", [])):
            cluster["validation"]["checked_at"] = DATE
            cluster["content_review"]["checked_at"] = DATE
    clusters["meta"]["updated_at"] = DATE

    search = load_json(data_dir / "search-protocol.json")
    for stream_id in ("NS-09", "NS-10", "NS-12", "NS-13"):
        stream = next(item for item in search["search_streams"] if item["id"] == stream_id)
        for source_id in sorted(UPDATES):
            if source_id not in stream["source_ids"]:
                stream["source_ids"].append(source_id)
        stream["source_ids"].sort(key=lambda source_id: int(source_id[1:]))
        stream["status"] = "second_pass_recorded"
    search["search_runs"].append(
        {
            "id": "NS-RUN-2026-09-24-07",
            "date": DATE,
            "queries": [
                "machine learning optimize spinal cord stimulation patent",
                "ECAP spinal cord injury therapy patent",
                "adaptive neural interface federated learning patent",
                "multidimensional patient features neurostimulation patent",
                "ECAP filtered waveform channel impulse response patent",
                "multimodal wearable pain estimate closed loop patent",
                "exact CN122075919A",
            ],
            "primary_urls": [spec["url"] for spec in UPDATES.values()],
            "new_mechanism_classes": ["ML SCS parameter search", "ECAP-guided SCI functional control", "population-relative multimodal neurostimulation control", "explicit ECAP/body-channel signal separation", "wearable pain-estimate stimulation loop"],
            "direct_drosophila_ecap_scs_analogue_found": False,
            "saturation": False,
        }
    )

    novelty = load_json(data_dir / "novelty-landscape.json")
    analogue_ids = [source_id for source_id in sorted(UPDATES) if source_id != "S272"]
    for variant in novelty["variants"]:
        for source_id in analogue_ids:
            if source_id not in variant["closest_analogue_refs"]:
                variant["closest_analogue_refs"].append(source_id)
        for stream_id in ("NS-09", "NS-10", "NS-12", "NS-13"):
            if stream_id not in variant["search_trace_ids"]:
                variant["search_trace_ids"].append(stream_id)
        suffix = " Patent review adds ML SCS-parameter search (S098), ECAP-guided functional control (S099), federated adaptive neural interfaces (S144), population-relative multimodal control (S240), explicit body-channel/ECAP separation (S241), and a wearable multimodal stimulation loop (S245); none combines Drosophila connectome dynamics with a validated human ECAP/SCS transfer experiment."
        if suffix not in variant["difference_from_analogues"]:
            variant["difference_from_analogues"] += suffix
    novelty["meta"]["generated_at"] = DATE

    validation_log = load_json(data_dir / "validation-log.json")
    validation_log.setdefault("searches", []).append(
        {
            "search_id": "NEUROMODULATION-PATENTS-2026-09-24-01",
            "date": DATE,
            "stream": "ECAP, SCS optimization, adaptive neural interfaces and wearable closed-loop patents",
            "query": "exact publication number followed by full patent description and claims",
            "urls_reviewed": [spec["url"] for spec in UPDATES.values()],
            "source_ids": sorted(UPDATES),
            "decision": "five full patent disclosures verified, one recent disclosure partially verified, and one identifier closed as terminal unavailable",
        }
    )
    validation_log["meta"]["checked_at"] = DATE

    audit = load_json(data_dir / "audit-report.json")
    audit["current_corpus"]["validation_statuses"] = dict(sorted(statuses.items()))
    audit["meta"]["generated_at"] = DATE
    audit["neuromodulation_patent_review"] = {
        "checked_at": DATE,
        "reviewed_source_ids": sorted(UPDATES),
        "finding": "several component-level analogues narrow novelty, but patents provide no empirical Drosophila-to-ECAP-to-SCS transfer validation",
    }
    completeness = load_json(data_dir / "completeness-report.json")
    completeness.update(completeness_summary(sources))
    completeness["meta"]["generated_at"] = DATE
    return {
        "records.json": records,
        "evidence-matrix.json": evidence,
        "clusters.json": clusters,
        "search-protocol.json": search,
        "novelty-landscape.json": novelty,
        "validation-log.json": validation_log,
        "audit-report.json": audit,
        "completeness-report.json": completeness,
    }


def validate_outputs(outputs: dict[str, dict[str, Any]], data_dir: Path = DATA) -> None:
    with tempfile.TemporaryDirectory(prefix="research-neuromodulation-patents-") as temporary:
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
        snapshot = snapshot_repository(DATA, label="pre-neuromodulation-patent-review")
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
        report = validate_repository(DATA)
        if not report["ok"]:
            raise RuntimeError(f"restore {snapshot}: {'; '.join(report['errors'])}")
    print(json.dumps({"ok": True, "applied": args.apply, "reviewed": sorted(UPDATES), "snapshot": str(snapshot) if snapshot else None}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
