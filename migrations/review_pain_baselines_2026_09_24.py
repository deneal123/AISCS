"""Review acute/chronic pain baselines and a Drosophila heat-response abstract."""

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
BATCH_ID = "pain-baseline-review-2026-09-24"

UPDATES: dict[str, dict[str, Any]] = {
    "S005": {
        "url": "https://researchsystem.canberra.edu.au/ws/portalfiles/portal/118630433/3737281.pdf",
        "fields": {
            MODALITY: "Multimodal physiological signals including ECG, EDA, EMG, EEG, PPG and respiration",
            TASK: "Systematic review of multimodal fusion for acute experimental-pain assessment",
            METHOD: "PRISMA-based search of Scopus, IEEE Xplore and Google Scholar in September 2024 with backward/forward snowballing",
            DATASET: "31 studies published from January 2015 through September 2024; 20 used public datasets including BioVid, X-ITE and SenseEmotion",
            PERFORMANCE: "No pooled effect or common metric; the review tabulates heterogeneous study-specific results",
            CROSS_SUBJECT: "not_applicable: systematic review",
            LIMITATIONS: "Only three bibliographic databases were searched, and image/video-led studies, chronic pain, animal studies and inaccessible papers were excluded by design. The review does not pool metrics or prove that multimodal fusion generalizes across participants or clinical settings.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "31 acute-pain multimodal studies, predominantly controlled experimental datasets",
            "subject_domain": "mixed",
            "modalities": ["eeg", "ecg", "eda", "emg", "bvp_ppg", "other"],
            "sample_size": 31,
            "target_construct": "experimental_pain_class",
            "target_label": "Study-specific acute-pain detection or intensity targets",
            "access_status": "open",
            "evidence_role": "method_baseline",
        },
        "validation": {
            "status": "verified_primary",
            "full_text_status": "checked",
            "split_unit": "study",
            "cross_subject": "not_applicable",
            "external_validation": "not_applicable",
            "calibration": "not_applicable",
            "uncertainty": "not_applicable",
        },
        "risk_flags": ["claim_not_supported"],
        "locator": "Final published PDF, Sections 3.2-4.2 and 6, PRISMA Figure 1",
        "claim": "A systematic review maps multimodal physiological fusion in 31 acute-pain studies but does not provide a pooled generalization estimate.",
        "verified": "The open final PDF confirms the search date, databases, eligibility criteria, study count, public datasets and stated review limitations.",
        "permitted": "Use to map modalities, fusion designs and recurring validation gaps; do not use as a pooled accuracy estimate or chronic-pain/SCS evidence.",
    },
    "S014": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/39222459/",
        "pmid": "39222459",
        "fields": {
            MODALITY: "EEG, photoplethysmography, ECG and facial temperature",
            TASK: "Classification of chronic-pain patients versus normal controls",
            METHOD: "Handcrafted biosignal features, feature-combination optimization and a classification model",
            DATASET: "59 subjects, including 26 chronic-pain patients, in the primary abstract",
            PERFORMANCE: "Primary abstract reports AUROC improvement from 0.802 to 0.864; 17 of 112 features differed significantly between groups",
            CROSS_SUBJECT: None,
            LIMITATIONS: "The primary abstract does not establish the participant split, confidence intervals, calibration, external validation or whether feature selection was nested within resampling. The target is patient-versus-control status, not continuous pain severity or treatment response.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "59 participants, including 26 chronic-pain patients",
            "subject_domain": "human_clinical",
            "modalities": ["eeg", "bvp_ppg", "ecg", "thermal_video"],
            "sample_size": 59,
            "target_construct": "clinical_function",
            "target_label": "Chronic-pain patient versus normal control",
            "access_status": "restricted",
            "evidence_role": "human_validation",
        },
        "validation": {
            "status": "partially_verified",
            "full_text_status": "metadata_only",
            "split_unit": "unavailable_after_search",
            "cross_subject": "unavailable_after_search",
            "external_validation": "unavailable_after_search",
            "calibration": "unavailable_after_search",
            "uncertainty": "unavailable_after_search",
        },
        "risk_flags": ["metadata_only", "missing_cross_subject_validation", "claim_not_supported"],
        "locator": "PubMed PMID 39222459, Abstract: Methods and Results",
        "claim": "A 59-participant study reports multimodal separation of chronic-pain patients from controls.",
        "verified": "The primary abstract confirms modalities, cohort composition, feature count and AUROC values.",
        "permitted": "Use as an abstract-level clinical classification baseline; do not call it pain-intensity estimation, external validation or an SCS outcome model.",
    },
    "S017": {
        "url": "https://doi.org/10.1109/JIOT.2025.3590401",
        "fields": {
            MODALITY: "Single-lead ECG",
            TASK: "Pain-tolerance stimulus versus no-pain classification",
            METHOD: "ResNet feature compression, self-attention pain-feature extraction and cross-attention fusion with large-kernel convolution",
            DATASET: "Public BioVid experimental heat-pain dataset; cohort and split details unavailable in the accessible indexed abstract",
            PERFORMANCE: "Indexed abstract reports 72.41% accuracy, 0.43 GFLOPs and 65.6% lower computational complexity than compared transformer approaches",
            CROSS_SUBJECT: None,
            LIMITATIONS: "The IEEE full text was unavailable. The split unit, uncertainty, calibration and independent dataset evaluation could not be checked. BioVid is controlled experimental heat pain; language about chronic-pain monitoring is proposed application, not demonstrated chronic-pain validation.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "BioVid experimental heat-pain participants; exact cohort use unavailable in the abstract",
            "subject_domain": "human_healthy",
            "modalities": ["ecg"],
            "sample_size": None,
            "target_construct": "experimental_pain_class",
            "target_label": "Pain-tolerance heat stimulus versus no-pain state",
            "access_status": "restricted",
            "evidence_role": "method_baseline",
        },
        "validation": {
            "status": "partially_verified",
            "full_text_status": "metadata_only",
            "split_unit": "unavailable_after_search",
            "cross_subject": "unavailable_after_search",
            "external_validation": "no",
            "calibration": "unavailable_after_search",
            "uncertainty": "unavailable_after_search",
        },
        "risk_flags": ["metadata_only", "missing_cross_subject_validation", "claim_not_supported"],
        "locator": "Crossref DOI metadata and indexed author abstract; IEEE full text unavailable",
        "claim": "An ECG model reports BioVid pain-tolerance-versus-baseline classification and reduced computational cost.",
        "verified": "Bibliographic identity and abstract-level architecture, dataset, target and author-reported values were checked.",
        "permitted": "Use as an abstract-level efficient ECG baseline for experimental pain only; do not infer chronic-pain or subject-independent validation.",
    },
    "S026": {
        "url": "https://www.jstage.jst.go.jp/article/hikakuseiriseika/31/4/31_151/_pdf",
        "fields": {
            MODALITY: "Whole-animal protective behavior under noxious heat",
            TASK: "Behavioral assay of brain-independent noxious-heat responses in decapitated adult Drosophila",
            METHOD: "Hotplate exposure at 44 degrees C comparing wild-type and painless-mutant decapitated flies",
            DATASET: "Conference abstract; sample counts and trial counts are not reported",
            PERFORMANCE: "Wild-type decapitated flies tumbled rather than jumped at 44 degrees C; tumbling frequency was significantly reduced in painless mutants, without a reported effect size",
            CROSS_SUBJECT: "not_applicable: behavioral conference abstract without a predictive split",
            LIMITATIONS: "This is a short meeting abstract, not a full experimental article. It reports neither sample size nor effect size. Decapitation changes the preparation, tumbling is a protective nociceptive phenotype, and neither the assay nor the painless gene establishes subjective pain.",
        },
        "evidence": {
            "species": "Drosophila melanogaster",
            "population": "Decapitated adult wild-type and painless-mutant flies",
            "subject_domain": "drosophila_adult",
            "modalities": ["behavior"],
            "sample_size": None,
            "target_construct": "protective_behavior",
            "target_label": "Tumbling response to 44 degrees C noxious heat",
            "access_status": "open",
            "evidence_role": "simulation_foundation",
        },
        "validation": {
            "status": "verified_primary",
            "full_text_status": "checked",
            "split_unit": "not_applicable",
            "cross_subject": "not_applicable",
            "external_validation": "no",
            "calibration": "not_applicable",
            "uncertainty": "not_reported",
        },
        "risk_flags": ["animal_to_human_transfer_unvalidated", "claim_not_supported"],
        "locator": "J-STAGE meeting-abstract volume, p. 160, abstract 'Novel behavioral assay of noxious heat responses in Drosophila using decapitated flies'",
        "claim": "A meeting abstract separates brain-dependent jumping from a brain-independent tumbling response to noxious heat in adult Drosophila.",
        "verified": "The primary meeting abstract confirms the 44 degrees C preparation, wild-type tumbling and reduced tumbling in painless mutants.",
        "permitted": "Use as preliminary evidence for a distinct protective-behavior observable; do not call it subjective pain, a spinal-cord model or a quantified validation dataset.",
    },
    "S164": {
        "url": "https://vbn.aau.dk/en/publications/transformer-and-attention-based-models-for-automated-pain-assessm/",
        "fields": {
            MODALITY: "Visual, physiological, EEG, audio and multimodal pain-assessment inputs",
            TASK: "Structured narrative review of transformer- and attention-based automated pain assessment",
            METHOD: "PRISMA-informed narrative synthesis of studies published from 2015 through 2025",
            DATASET: "35 peer-reviewed studies spanning experimental and clinical tasks",
            PERFORMANCE: "No meta-analysis; the abstract notes that some controlled binary benchmarks exceed 90% but performance often falls under LOSO, subject-independent or cross-dataset evaluation",
            CROSS_SUBJECT: "not_applicable: review",
            LIMITATIONS: "Heterogeneous targets, datasets, modalities, metrics and validation protocols precluded quantitative pooling. Screening and extraction were performed by one reviewer and no formal protocol was registered. Reported high benchmark scores are not transferable estimates of clinical performance.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "35 heterogeneous automated-pain-assessment studies",
            "subject_domain": "mixed",
            "modalities": ["eeg", "ecg", "eda", "emg", "bvp_ppg", "video_face", "audio", "other"],
            "sample_size": 35,
            "target_construct": "experimental_pain_class",
            "target_label": "Heterogeneous pain detection and estimation targets across included studies",
            "access_status": "open",
            "evidence_role": "method_baseline",
        },
        "validation": {
            "status": "partially_verified",
            "full_text_status": "metadata_only",
            "split_unit": "study",
            "cross_subject": "not_applicable",
            "external_validation": "not_applicable",
            "calibration": "not_applicable",
            "uncertainty": "not_applicable",
        },
        "risk_flags": ["metadata_only", "claim_not_supported"],
        "locator": "Aalborg University research record, Abstract and bibliographic metadata",
        "claim": "A 35-study narrative review documents a generalization gap between controlled pain benchmarks and clinically realistic settings.",
        "verified": "The institutional primary record confirms study count, synthesis type, lack of meta-analysis and the explicit limitations of single-reviewer extraction and unregistered protocol.",
        "permitted": "Use as a structured map of transformer/attention prior art and validation gaps, not as pooled evidence for a particular model or clinical performance.",
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
            "target_variable": source["evidence"]["target_label"],
            "population_or_data": source["evidence"]["population"],
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
    ns03 = next(item for item in search["search_streams"] if item["id"] == "NS-03")
    if "S026" not in ns03["source_ids"]:
        ns03["source_ids"].append("S026")
    ns17 = next(item for item in search["search_streams"] if item["id"] == "NS-17")
    for source_id in ("S005", "S014", "S017", "S164"):
        if source_id not in ns17["source_ids"]:
            ns17["source_ids"].append(source_id)
    ns17["source_ids"].sort(key=lambda source_id: int(source_id[1:]))
    search["search_runs"].append(
        {
            "id": "NS-RUN-2026-09-24-05",
            "date": DATE,
            "queries": ["multimodal acute pain fusion systematic review full text", "chronic pain biosignal classification primary abstract", "BioVid ECG efficient pain classification", "Drosophila decapitated noxious heat painless", "transformer attention pain systematic review generalization"],
            "primary_urls": [spec["url"] for spec in UPDATES.values()],
            "new_mechanism_classes": ["brain-independent Drosophila heat-evoked protective behavior", "multimodal generalization-gap synthesis"],
            "direct_drosophila_ecap_scs_analogue_found": False,
            "saturation": False,
        }
    )

    novelty = load_json(data_dir / "novelty-landscape.json")
    for variant in novelty["variants"]:
        for source_id in ("S005", "S026", "S164"):
            if source_id not in variant["closest_analogue_refs"]:
                variant["closest_analogue_refs"].append(source_id)
        for stream_id in ("NS-03", "NS-17"):
            if stream_id not in variant["search_trace_ids"]:
                variant["search_trace_ids"].append(stream_id)
        suffix = " S026 supports only a brain-independent fly protective-behavior observable, while S005 and S164 document heterogeneous human pain baselines and generalization gaps; none supplies an ECAP formation operator or SCS validation bridge."
        if suffix not in variant["difference_from_analogues"]:
            variant["difference_from_analogues"] += suffix
    novelty["meta"]["generated_at"] = DATE

    validation_log = load_json(data_dir / "validation-log.json")
    validation_log.setdefault("searches", []).append(
        {
            "search_id": "PAIN-BASELINES-2026-09-24-01",
            "date": DATE,
            "stream": "acute/chronic human pain baselines and Drosophila noxious-heat behavior",
            "query": "exact DOI/title followed by primary repository, PubMed, publisher and full-text locator",
            "urls_reviewed": [spec["url"] for spec in UPDATES.values()],
            "source_ids": sorted(UPDATES),
            "decision": "two records upgraded from full primary material and three received bounded abstract-level evidence",
        }
    )
    validation_log["meta"]["checked_at"] = DATE

    audit = load_json(data_dir / "audit-report.json")
    audit["current_corpus"]["validation_statuses"] = dict(sorted(statuses.items()))
    audit["meta"]["generated_at"] = DATE
    audit["pain_baseline_review"] = {
        "checked_at": DATE,
        "reviewed_source_ids": sorted(UPDATES),
        "finding": "controlled pain, chronic-pain status and fly protective behavior remain distinct target constructs",
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
    with tempfile.TemporaryDirectory(prefix="research-pain-baselines-") as temporary:
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
        snapshot = snapshot_repository(DATA, label="pre-pain-baseline-review")
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
        report = validate_repository(DATA)
        if not report["ok"]:
            raise RuntimeError(f"restore {snapshot}: {'; '.join(report['errors'])}")
    print(json.dumps({"ok": True, "applied": args.apply, "reviewed": sorted(UPDATES), "snapshot": str(snapshot) if snapshot else None}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
