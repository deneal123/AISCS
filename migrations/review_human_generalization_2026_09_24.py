"""Review human cross-subject and cross-dataset pain-assessment baselines."""

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
BATCH_ID = "human-generalization-review-2026-09-24"

UPDATES: dict[str, dict[str, Any]] = {
    "S004": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/41564065/",
        "pmid": "41564065",
        "fields": {
            MODALITY: "Resting-state and pain-evoked EEG with localized high-activation brain-source features",
            TASK: "Inter-subject pain-intensity classification",
            METHOD: "Resting-EEG source-subject matching, source localization and remapping, transfer-suitability classification, balanced distribution adaptation and target pseudo-labeling",
            DATASET: "Real EEG datasets; dataset identities, cohort sizes and protocol details are unavailable in the accessible abstract",
            PERFORMANCE: "The abstract reports significant improvement over three approaches but provides no numerical metric",
            CROSS_SUBJECT: "yes: inter-subject transfer is the stated task; exact subject partition is unavailable in the abstract",
            LIMITATIONS: "Only the primary PubMed abstract was accessible. Dataset identity, cohort, exact split, numerical results, calibration, uncertainty and independent external validation were not established. The abstract's phrase 'clinically viable' is not evidence of clinical validation.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "Participants in real EEG datasets; cohort and health status unavailable in the abstract",
            "subject_domain": "unavailable_after_search",
            "modalities": ["eeg"],
            "sample_size": None,
            "target_construct": "experimental_pain_class",
            "target_label": "Pain-intensity classes inferred from resting and pain-evoked EEG",
            "access_status": "restricted",
            "evidence_role": "method_baseline",
        },
        "validation": {
            "status": "partially_verified",
            "full_text_status": "metadata_only",
            "split_unit": "participant",
            "cross_subject": "yes",
            "external_validation": "unavailable_after_search",
            "calibration": "unavailable_after_search",
            "uncertainty": "unavailable_after_search",
        },
        "risk_flags": ["metadata_only", "claim_not_supported"],
        "locator": "PubMed PMID 41564065, Abstract: Methods, Results and Conclusion",
        "claim": "The primary abstract describes an EEG transfer framework for inter-subject pain-intensity classification.",
        "verified": "The transfer components and qualitative comparison against three approaches are stated in the primary abstract; no numerical performance or cohort detail was available.",
        "permitted": "Use as an abstract-level inter-subject EEG method baseline only; do not claim quantified superiority, clinical validation or independent generalization.",
    },
    "S007": {
        "url": "https://doi.org/10.1109/JIOT.2026.3663683",
        "fields": {
            MODALITY: "Electrodermal activity represented in time, spectral and cepstral domains",
            TASK: "Binary and three-class experimental-pain classification with embedded inference",
            METHOD: "Lightweight multidomain one-dimensional CNN deployed on Raspberry Pi 5",
            DATASET: "AI4Pain and BioVid; cohort sizes are not reported in the accessible indexed abstract",
            PERFORMANCE: "Indexed abstract reports 92.08% binary accuracy, 71.91% three-class accuracy, 102-119 ms latency, 27.5-30.6% CPU load and 4.6-4.8 W power",
            CROSS_SUBJECT: "yes: leave-one-subject-out cross-validation",
            LIMITATIONS: "The DOI metadata and an indexed abstract were accessible, but the IEEE full text was not. Dataset-specific metrics, participant counts, confidence intervals, calibration and truly independent external validation could not be checked. Both datasets concern experimental pain and do not establish chronic-pain or SCS validity.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "Participants in the AI4Pain and BioVid experimental-pain datasets; counts unavailable in the accessible abstract",
            "subject_domain": "human_healthy",
            "modalities": ["eda"],
            "sample_size": None,
            "target_construct": "experimental_pain_class",
            "target_label": "No Pain versus High Pain; No Pain versus Low Pain versus High Pain",
            "access_status": "restricted",
            "evidence_role": "method_baseline",
        },
        "validation": {
            "status": "partially_verified",
            "full_text_status": "metadata_only",
            "split_unit": "participant",
            "cross_subject": "yes",
            "external_validation": "no",
            "calibration": "unavailable_after_search",
            "uncertainty": "unavailable_after_search",
        },
        "risk_flags": ["metadata_only", "claim_not_supported"],
        "locator": "Crossref DOI metadata and indexed author abstract; full IEEE text unavailable",
        "claim": "MDNet reports LOSO evaluation on AI4Pain and BioVid and an embedded Raspberry Pi implementation.",
        "verified": "Bibliographic identity and abstract-level task, datasets, LOSO protocol, reported accuracies and device measurements were checked; full-text methods were not.",
        "permitted": "Use the values as author-reported abstract results and as an EDA/embedded baseline; do not claim external clinical or SCS validation.",
    },
    "S008": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/41499809/",
        "pmid": "41499809",
        "fields": {
            MODALITY: "EEG frequency features",
            TASK: "Low-versus-high experimental-pain classification",
            METHOD: "One-dimensional CNN with DeepSHAP frequency attribution",
            DATASET: "EEG from 50 subjects exposed to low and high pain stimuli",
            PERFORMANCE: "Primary abstract reports 95.85% accuracy; beta 14-15 Hz was associated with high-pain decisions, while alpha 11-12 Hz, theta and delta contributed to lower-pain decisions",
            CROSS_SUBJECT: "yes: leave-one-subject-out cross-validation",
            LIMITATIONS: "The primary abstract confirms the cohort, LOSO design and accuracy, but not confidence intervals, per-subject dispersion, calibration, uncertainty, dataset identity or independent external validation. DeepSHAP associations do not establish causal pain biomarkers.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "50 subjects exposed to controlled low and high pain stimuli",
            "subject_domain": "human_healthy",
            "modalities": ["eeg"],
            "sample_size": 50,
            "target_construct": "experimental_pain_class",
            "target_label": "Low versus high pain stimulus class",
            "access_status": "open",
            "evidence_role": "method_baseline",
        },
        "validation": {
            "status": "partially_verified",
            "full_text_status": "metadata_only",
            "split_unit": "participant",
            "cross_subject": "yes",
            "external_validation": "no",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
        },
        "risk_flags": ["metadata_only", "claim_not_supported"],
        "locator": "PubMed PMID 41499809, Abstract: Approach and Main Results",
        "claim": "A 50-subject EEG study reports LOSO low/high pain classification and post-hoc DeepSHAP frequency attribution.",
        "verified": "The primary abstract confirms 50 subjects, LOSO, 95.85% accuracy and the reported frequency associations.",
        "permitted": "Use as an author-reported experimental EEG baseline; do not treat attribution as causal or extrapolate to chronic pain and SCS.",
    },
    "S070": {
        "url": "https://arxiv.org/abs/2508.11691",
        "fields": {
            MODALITY: "64-channel EEG downsampled to 250 Hz",
            TASK: "Binary discrimination of thermal painful stimulation from aversive non-painful auditory stimulation",
            METHOD: "CSP+SVM, MDM, tangent-space logistic regression, ShallowFBCSPNet, Deep4Net, EEGNetv4, EEGConformer and Gaussian Graph Network benchmarks",
            DATASET: "108 participants (67 female; mean age 25, SD 6.3), 500 epochs per participant, recorded at two academic sites; preprocessed dataset released in BIDS form",
            PERFORMANCE: "Cross-participant accuracy: CSP+SVM 0.4734 +/- 0.164, MDM 0.54261 +/- 0.102, TSLR 0.57004 +/- 0.091, ShallowFBCSPNet 0.8512 +/- 0.205, Deep4Net 0.8606 +/- 0.207, EEGNetv4 0.6500 +/- 0.120, EEGConformer 0.6600 +/- 0.205, GGN 0.8523 +/- 0.193",
            CROSS_SUBJECT: "yes: one participant held out for test; 30% of remaining participants held out for validation",
            LIMITATIONS: "The target is stimulus modality, not pain intensity or clinical pain. Participants had no chronic pain, and performance variability across held-out participants remained high. The paper reports no independent external dataset, calibration or clinical/SCS evaluation.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "108 adults without chronic pain, neurological or psychiatric disorders, recorded at two academic sites",
            "subject_domain": "human_healthy",
            "modalities": ["eeg"],
            "sample_size": 108,
            "target_construct": "noxious_stimulus",
            "target_label": "Thermal painful versus aversive non-painful auditory stimulus modality",
            "access_status": "open",
            "evidence_role": "human_validation",
        },
        "validation": {
            "status": "verified_primary",
            "full_text_status": "checked",
            "split_unit": "participant",
            "cross_subject": "yes",
            "external_validation": "no",
            "calibration": "not_reported",
            "uncertainty": "yes",
        },
        "risk_flags": ["claim_not_supported"],
        "locator": "arXiv:2508.11691v1, Sections 3.1-4.2, Tables 1-2 and Discussion",
        "claim": "A 108-participant EEG benchmark quantifies the loss of generalization from within-participant to held-out-participant stimulus-modality classification.",
        "verified": "The primary full text confirms participant-level splitting, public data, cohort composition and the reported per-model cross-participant accuracies.",
        "permitted": "Use as an open cross-participant EEG benchmark and split-design baseline, while stating that its target is stimulus modality rather than subjective pain intensity.",
    },
    "S072": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/41192117/",
        "pmid": "41192117",
        "fields": {
            MODALITY: "Electrodermal activity and electromyography",
            TASK: "Multiclass experimental-pain intensity classification",
            METHOD: "LSTM with spatial attention, adaptive modality weighting, focal loss and jump-reduction undersampling",
            DATASET: "Eleven sub-datasets from the X-ITE pain database",
            PERFORMANCE: "Primary abstract reports a mean accuracy improvement of 3.88 percentage points across 11 sub-datasets and 7.12 points on the R-ETD subset over compared approaches",
            CROSS_SUBJECT: None,
            LIMITATIONS: "Only the primary abstract was accessible. Participant count, split unit, exact class definitions, absolute performance, confidence intervals, calibration and external validation were not established. X-ITE is an experimental-pain database; the word 'clinical' in the title does not establish clinical-outcome validation.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "Participants represented by eleven X-ITE sub-datasets; cohort size unavailable in the abstract",
            "subject_domain": "human_healthy",
            "modalities": ["eda", "emg"],
            "sample_size": None,
            "target_construct": "experimental_pain_class",
            "target_label": "Pain-intensity classes in X-ITE sub-datasets",
            "access_status": "restricted",
            "evidence_role": "method_baseline",
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
        "risk_flags": ["metadata_only", "claim_not_supported"],
        "locator": "PubMed PMID 41192117, Abstract",
        "claim": "An EDA/EMG fusion model reports relative improvements across eleven X-ITE sub-datasets.",
        "verified": "The primary abstract confirms the modalities, method components, X-ITE basis and two relative improvement values.",
        "permitted": "Use as an abstract-level experimental multimodal baseline; do not call it clinically validated or infer participant-level generalization.",
    },
    "S088": {
        "url": "https://doi.org/10.1109/ISDA70544.2026.11606012",
        "fields": {
            MODALITY: "Multimodal physiological signals; exact channels unavailable from the primary metadata",
            TASK: "Cross-domain multimodal pain detection",
            METHOD: "DANN-Transformer with supervised contrastive warmup and test-time augmentation, as stated in the title",
            DATASET: None,
            PERFORMANCE: None,
            CROSS_SUBJECT: None,
            LIMITATIONS: "Crossref confirms the paper identity, authors, venue and DOI, but the IEEE full text and a publisher-deposited abstract were unavailable. Dataset, cohort, modalities, split, metrics and claimed state of the art therefore remain unverified and must not be inferred from third-party indexes.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": None,
            "subject_domain": "unavailable_after_search",
            "modalities": [],
            "sample_size": None,
            "target_construct": "experimental_pain_class",
            "target_label": "Cross-domain pain-detection class; exact label definition unavailable",
            "access_status": "restricted",
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
        "risk_flags": ["metadata_only", "claim_not_supported"],
        "locator": "Crossref record for DOI 10.1109/ISDA70544.2026.11606012; no primary abstract or full text available",
        "claim": "A 2026 ISDA proceedings paper with a DANN-Transformer cross-domain pain-detection title exists.",
        "verified": "Only title, authors, venue, publication date and DOI were verified from Crossref.",
        "permitted": "Use as unresolved bibliographic prior art only; do not cite datasets, modalities, metrics or generalization claims until primary text is obtained.",
    },
}


def build_outputs(data_dir: Path = DATA) -> dict[str, dict[str, Any]]:
    records = load_json(data_dir / "records.json")
    found: set[str] = set()
    sources: list[dict[str, Any]] = []
    for record in records["sources"]:
        if record["id"] in UPDATES:
            record = _update_record(record, UPDATES[record["id"]])
            if record["id"] == "S070":
                relations = list(record.get("relations", []))
                relation = {
                    "type": "version_of",
                    "target_id": None,
                    "external_id": "arxiv:2508.11691v1",
                    "note": "Open author manuscript corresponding to the IEEE MLSP proceedings article.",
                }
                if relation not in relations:
                    relations.append(relation)
                record["relations"] = relations
            found.add(record["id"])
        sources.append(record)
    if found != set(UPDATES):
        raise ValueError(f"missing source IDs: {sorted(set(UPDATES) - found)}")
    records["sources"] = sources
    statuses = Counter(source["validation"]["status"] for source in sources)
    records["meta"].update(
        {
            "records_count": len(sources),
            "verified_primary_count": statuses["verified_primary"],
            "updated_at": DATE,
        }
    )
    by_id = {source["id"]: source for source in sources}

    evidence = load_json(data_dir / "evidence-matrix.json")
    single_rows = {
        row["source_ids"][0]: row
        for row in evidence["rows"]
        if len(row.get("source_ids", [])) == 1
    }
    for source_id, spec in UPDATES.items():
        source = by_id[source_id]
        row = single_rows.get(source_id)
        payload = {
            "batch_id": BATCH_ID,
            "claim": spec["claim"],
            "target_variable": source["evidence"]["target_label"],
            "population_or_data": source["evidence"]["population"] or "population unavailable after documented search",
            "source_ids": [source_id],
            "verified_evidence": spec["verified"],
            "limitations": source[LIMITATIONS],
            "permitted_conclusion": spec["permitted"],
            "locators": [{"source_id": source_id, "url": spec["url"], "locator": spec["locator"]}],
        }
        if row is None:
            evidence["rows"].append(payload)
        else:
            row.update(payload)
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
    stream = next((item for item in search["search_streams"] if item["id"] == "NS-17"), None)
    stream_payload = {
        "id": "NS-17",
        "topic": "human cross-subject and cross-dataset experimental-pain baselines",
        "status": "initial_pass_recorded",
        "source_ids": sorted(UPDATES),
        "queries_required": ["exact DOI and title", "primary abstract or full text", "dataset and split verification"],
        "snowballing": "backward_and_forward_required",
    }
    if stream is None:
        search["search_streams"].append(stream_payload)
    else:
        stream.update(stream_payload)
    search["search_runs"].append(
        {
            "id": "NS-RUN-2026-09-24-04",
            "date": DATE,
            "queries": [
                "inter-subject EEG pain classification primary abstract",
                "LOSO EDA pain AI4Pain BioVid primary record",
                "EEG painful thermal versus aversive auditory cross-participant",
                "X-ITE EDA EMG pain fusion primary abstract",
                "DANN Transformer cross-domain pain IEEE primary record",
            ],
            "primary_urls": [spec["url"] for spec in UPDATES.values()],
            "new_mechanism_classes": ["resting-EEG-guided transfer", "embedded multidomain EDA CNN", "participant-held-out EEG stimulus benchmark", "cross-dataset adversarial pain adaptation"],
            "direct_drosophila_ecap_scs_analogue_found": False,
            "saturation": False,
        }
    )

    novelty = load_json(data_dir / "novelty-landscape.json")
    for variant in novelty["variants"]:
        for source_id in ("S007", "S070", "S088"):
            if source_id not in variant["closest_analogue_refs"]:
                variant["closest_analogue_refs"].append(source_id)
        if "NS-17" not in variant["search_trace_ids"]:
            variant["search_trace_ids"].append("NS-17")
        suffix = " S007 and S070 provide human experimental-pain cross-subject baselines, while S088 is unresolved cross-dataset prior art; none implements a Drosophila-connectome-to-physical-ECAP-to-SCS chain."
        if suffix not in variant["difference_from_analogues"]:
            variant["difference_from_analogues"] += suffix
    novelty["meta"]["generated_at"] = DATE

    validation_log = load_json(data_dir / "validation-log.json")
    validation_log.setdefault("searches", []).append(
        {
            "search_id": "HUMAN-GENERALIZATION-2026-09-24-01",
            "date": DATE,
            "stream": "human cross-subject and cross-dataset pain-assessment baselines",
            "query": "exact DOI/title followed by PubMed, Crossref, publisher and open author manuscript",
            "urls_reviewed": [spec["url"] for spec in UPDATES.values()],
            "source_ids": sorted(UPDATES),
            "decision": "five records received abstract/full-text evidence and one remains terminal metadata-only because primary content was unavailable",
        }
    )
    validation_log["meta"]["checked_at"] = DATE

    audit = load_json(data_dir / "audit-report.json")
    audit["current_corpus"].update(
        {"canonical_sources": len(sources), "validation_statuses": dict(sorted(statuses.items()))}
    )
    audit["meta"]["generated_at"] = DATE
    audit["human_generalization_review"] = {
        "checked_at": DATE,
        "reviewed_source_ids": sorted(UPDATES),
        "finding": "human cross-subject baselines exist, but their targets and access levels differ; none validates Drosophila-to-ECAP-to-SCS transfer",
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
    with tempfile.TemporaryDirectory(prefix="research-human-generalization-") as temporary:
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
        snapshot = snapshot_repository(DATA, label="pre-human-generalization-review")
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
        report = validate_repository(DATA)
        if not report["ok"]:
            raise RuntimeError(f"restore {snapshot}: {'; '.join(report['errors'])}")
    print(
        json.dumps(
            {
                "ok": True,
                "applied": args.apply,
                "reviewed": sorted(UPDATES),
                "snapshot": str(snapshot) if snapshot else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
