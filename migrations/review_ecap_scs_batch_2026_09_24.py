"""Review priority ECAP/SCS sources and register a newly found patent analogue."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from service.completeness import RESOLVED_PATHS, completeness_summary, migrate_record
from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-24"

(
    AUTHORS,
    YEAR,
    VENUE,
    MODALITY,
    TASK,
    METHOD,
    DATASET,
    PERFORMANCE,
    CROSS_SUBJECT,
    LIMITATIONS,
) = RESOLVED_PATHS[:10]

UPDATES: dict[str, dict[str, Any]] = {
    "S006": {
        "url": "https://openalex.org/W4403104801",
        "fields": {
            MODALITY: "Epidural SCS ECAP waveforms",
            TASK: "Detection of ECAPs elicited by epidural spinal cord stimulation",
            METHOD: None,
            DATASET: None,
            PERFORMANCE: None,
            CROSS_SUBJECT: None,
            LIMITATIONS: "Only bibliographic metadata and the official conference-program listing were accessible. Methods, cohort, split and performance were not recoverable from a primary full text and must not be inferred from the later related patent.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": None,
            "subject_domain": "human_clinical",
            "modalities": ["ecap"],
            "sample_size": None,
            "target_construct": "technical_signal_quality",
            "target_label": "ECAP presence in epidural SCS recordings",
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
        "risk_flags": ["metadata_only", "ecap_not_pain_measure"],
        "locator": "OpenAlex bibliographic record W4403104801 and NANS 2024 program listing; methods and results unavailable",
        "claim": "The conference abstract on neural-network ECAP detection exists under DOI 10.1016/j.neurom.2024.06.321.",
        "verified": "Title, authors, venue, year, DOI and conference presentation were confirmed; no method or metric was extracted.",
        "permitted": "Use as prior-art identity only; do not attribute a cohort, accuracy, validation design or clinical effect.",
    },
    "S034": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/40879389/",
        "pmid": "40879389",
        "fields": {
            MODALITY: "Spinal imaging radiomics, clinical variables and patient-reported outcomes",
            TASK: "Prediction of 50% and 70% SCS responder targets",
            METHOD: "Machine-learning models with systematic feature selection integrating radiomics and clinical data",
            DATASET: "The authors describe the largest US SCS database; sample size and site composition are not reported in the accessible abstract",
            PERFORMANCE: "50% target: accuracy 90.00%, AUC 91.40%, sensitivity 84.62%, specificity 94.12%; 70% target: accuracy 90.00%, AUC 86.11%, sensitivity 83.33%, specificity 91.67%",
            CROSS_SUBJECT: None,
            LIMITATIONS: "The accessible PubMed abstract confirms author-reported metrics but not sample size, split construction, leakage controls, calibration or independent external validation. It cannot establish generalization or an ECAP mechanism.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "SCS patients in a US database; cohort size unavailable in the accessible abstract",
            "subject_domain": "human_clinical",
            "modalities": ["other", "clinical_outcome"],
            "sample_size": None,
            "target_construct": "scs_response",
            "target_label": "50% responder and 70% responder",
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
        "locator": "PubMed PMID 40879389, Abstract: Methods and Results",
        "claim": "The accessible abstract reports radiomics-plus-clinical prediction of two SCS responder thresholds.",
        "verified": "The two sets of accuracy, AUC, sensitivity and specificity values are confirmed in the primary bibliographic abstract.",
        "permitted": "Use the values as author-reported abstract results only; do not claim independent validation, calibration or robust generalization.",
    },
    "S046": {
        "url": "https://www.sciencedirect.com/science/article/abs/pii/S1094715925006439",
        "fields": {
            MODALITY: "Pre-operative scalp EEG, demographics, pain history and baseline outcome measures",
            TASK: "Three-month SCS responder classification",
            METHOD: "Recursive feature elimination followed by an explainable neural-network classifier",
            DATASET: "16 patients scheduled for permanent SCS implantation (age 64.5 +/- 11.7 years; 11 female)",
            PERFORMANCE: "Best neural network: accuracy 80.63% and Cohen's kappa 0.625",
            CROSS_SUBJECT: None,
            LIMITATIONS: "Conference supplement abstract with only 16 patients. The accessible text does not report split construction, calibration, uncertainty or independent validation; the composite responder definition is truncated in the preview.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "16 adults receiving permanent SCS for chronic back and/or leg pain",
            "subject_domain": "human_clinical",
            "modalities": ["eeg", "clinical_outcome"],
            "sample_size": 16,
            "target_construct": "scs_response",
            "target_label": "Composite responder within three months after implantation",
            "access_status": "restricted",
            "evidence_role": "method_baseline",
        },
        "validation": {
            "status": "verified_primary",
            "full_text_status": "checked",
            "split_unit": "not_reported",
            "cross_subject": "not_reported",
            "external_validation": "no",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
        },
        "risk_flags": ["claim_not_supported"],
        "locator": "ScienceDirect article preview, Methods, Results and Conclusion",
        "claim": "A 16-patient conference abstract reports an EEG-plus-clinical SCS responder classifier.",
        "verified": "The primary abstract confirms the cohort, selected EEG bands, accuracy and Cohen's kappa.",
        "permitted": "Use as a small exploratory SCS-response baseline, not as independent evidence of generalization or an ECAP result.",
    },
    "S078": {
        "url": "https://www.sciencedirect.com/book/9780443365287/a-modern-atlas-for-implantable-devices-of-the-spine-brain-and-nerve",
        "fields": {
            MODALITY: "Physiologic closed-loop SCS and ECAP feedback",
            TASK: "Clinical and technical overview of physiologic closed-loop controlled SCS",
            METHOD: "Book chapter",
            DATASET: None,
            PERFORMANCE: None,
            CROSS_SUBJECT: None,
            LIMITATIONS: "The publisher catalog confirms a paywalled book chapter (pages 283-297), but the full chapter was unavailable. It is a contextual review, not an empirical validation dataset.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": None,
            "subject_domain": "human_clinical",
            "modalities": ["ecap", "clinical_outcome"],
            "sample_size": None,
            "target_construct": "ecap_neural_recruitment",
            "target_label": "Physiologic feedback for closed-loop SCS",
            "access_status": "restricted",
            "evidence_role": "context_only",
        },
        "validation": {
            "status": "verified_metadata",
            "full_text_status": "unavailable",
            "split_unit": "not_applicable",
            "cross_subject": "not_applicable",
            "external_validation": "not_applicable",
            "calibration": "unavailable_after_search",
            "uncertainty": "unavailable_after_search",
        },
        "risk_flags": ["metadata_only", "ecap_not_pain_measure"],
        "locator": "ScienceDirect book catalog, Chapter 23, pages 283-297",
        "claim": "The publisher catalog identifies a chapter on physiologic closed-loop controlled SCS.",
        "verified": "Chapter title, authors, book, pages and DOI are confirmed; chapter claims were not extracted.",
        "permitted": "Use as bibliographic context only until lawful full-text review; use open guidelines or regulatory documents for technical claims.",
    },
    "S356": {
        "url": "https://assets.cureus.com/uploads/case_report/pdf/460390/20260202-302464-fuovtq.pdf",
        "fields": {
            MODALITY: "ECAP telemetry, stimulation parameters, NRS pain and functional outcomes",
            TASK: "Five-day ECAP-controlled closed-loop SCS trial for refractory lumbar radiculopathy",
            METHOD: "Single-patient open case report using an Evoke system and one 12-electrode lead at T7",
            DATASET: "One male patient in his 40s with refractory lumbar radiculopathy",
            PERFORMANCE: "During five days the device made approximately 24.2 million adjustments with 100% utilization; NRS changed from 7/10 to 1/10, sleep from 4 to 6 h, standing from 10 min to 4 h, and walking from 5 min to 1 h",
            CROSS_SUBJECT: "not_applicable: single case",
            LIMITATIONS: "Single uncontrolled five-day case with self-reported outcomes, possible placebo and contextual effects, and no generalizability. ECAP represents neural recruitment, not pain intensity.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "One male in his 40s with refractory lumbar radiculopathy",
            "subject_domain": "human_clinical",
            "modalities": ["ecap", "clinical_outcome"],
            "sample_size": 1,
            "target_construct": "scs_response",
            "target_label": "NRS pain and patient-reported sleep, standing and walking tolerance after a five-day trial",
            "access_status": "open",
            "evidence_role": "scs_ecap_validation",
        },
        "validation": {
            "status": "verified_primary",
            "full_text_status": "checked",
            "split_unit": "not_applicable",
            "cross_subject": "not_applicable",
            "external_validation": "no",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
        },
        "risk_flags": ["ecap_not_pain_measure", "claim_not_supported"],
        "locator": "Cureus PDF, Abstract; Case Presentation, pp. 2-4; Conclusions, p. 6",
        "claim": "A single five-day case documents ECAP-controlled SCS settings, device utilization and self-reported outcomes.",
        "verified": "The open full text confirms the one-patient design, lead location, pulse parameters, ECAP target and reported short-term outcomes.",
        "permitted": "Use as a technical case precedent only; do not infer comparative efficacy, causality, cross-subject validity or prediction performance.",
    },
    "S357": {
        "url": "https://jphv.ub.ac.id/index.php/jphv/article/view/306",
        "fields": {
            MODALITY: "Published EVOKE trial outcomes and health-economic model inputs",
            TASK: "Systematic review of ECAP-controlled closed-loop versus open-loop SCS",
            METHOD: "PRISMA review registered as PROSPERO CRD420251126075; Cochrane RoB 2 and CHEERS appraisal",
            DATASET: "One eligible randomized trial program (EVOKE), 134 randomized participants, plus its companion cost-utility analysis",
            PERFORMANCE: "Authors report >=50% pain-relief RR 1.47 (95% CI 1.27-1.70), >=80% pain-relief RR 0.18 (95% CI 0.08-0.27), and VAS mean difference -3.01 (95% CI -6.12 to 0.10); the direction and labeling of the >=80% statistic require full-text verification",
            CROSS_SUBJECT: "study-level synthesis of one trial program",
            LIMITATIONS: "The publisher page was inaccessible during review; extraction is limited to the publisher-deposited Crossref abstract. The synthesis relies on one trial program, has higher 36-month bias from missing data/selective reporting, and uses non-Indonesian economic inputs.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "134 randomized adults with chronic intractable back and/or leg pain in the EVOKE trial program",
            "subject_domain": "human_clinical",
            "modalities": ["ecap", "clinical_outcome"],
            "sample_size": 134,
            "target_construct": "scs_response",
            "target_label": "Pain response, disability, quality of life, opioid reduction and modeled cost utility",
            "access_status": "unavailable_after_search",
            "evidence_role": "scs_ecap_validation",
        },
        "validation": {
            "status": "partially_verified",
            "full_text_status": "unavailable",
            "split_unit": "study",
            "cross_subject": "yes",
            "external_validation": "no",
            "calibration": "not_applicable",
            "uncertainty": "yes",
        },
        "risk_flags": ["ecap_not_pain_measure", "claim_not_supported"],
        "locator": "Crossref publisher-deposited abstract for DOI 10.21776/ub.jphv.2026.007.01.07; Methods, Results and Conclusion",
        "claim": "A 2026 systematic review synthesizes ECAP-controlled versus open-loop SCS outcomes from the EVOKE program.",
        "verified": "The registered review design, one-program evidence base, participant count and abstract-reported effect estimates were confirmed.",
        "permitted": "Use as a single-program systematic synthesis with the reported limitations; do not treat it as independent replication or as proof that ECAP measures pain.",
    },
}


def _set_resolution_locators(record: dict[str, Any], locator: str) -> None:
    url = record["identifiers"]["exact_url"]
    for path, item in record["field_resolution"].items():
        item["checked_at"] = DATE
        item["locators"] = [{"url": url, "locator": f"{locator}; field {path}"}]
        if item["state"] == "reported":
            item["reason"] = "Value extracted from the checked primary page or full text."
        elif item["state"] == "not_reported":
            item["reason"] = "The property is not reported in the checked primary material."
        elif item["state"] == "not_applicable":
            item["reason"] = "The field is not applicable to this source type or study design."
        else:
            item["reason"] = "The value could not be established after the documented primary-source search."


def _update_record(record: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    updated = dict(record)
    for field, value in spec["fields"].items():
        updated[field] = value
    updated["identifiers"] = dict(record["identifiers"])
    updated["identifiers"]["exact_url"] = spec["url"]
    if spec.get("pmid"):
        updated["identifiers"]["pmid"] = spec["pmid"]
    updated["evidence"] = dict(spec["evidence"])
    updated["validation"] = {
        **record["validation"],
        **spec["validation"],
        "checked_at": DATE,
        "notes": spec["fields"][LIMITATIONS],
    }
    updated["risk_flags"] = list(spec["risk_flags"])
    updated = migrate_record(updated, checked_at=DATE)
    _set_resolution_locators(updated, spec["locator"])
    return updated


def _new_patent(template: dict[str, Any]) -> dict[str, Any]:
    title_key = list(template)[1]
    source_type_key = next(key for key, value in template.items() if value == "патент")
    relevance_key = list(template)[11]
    record = {
        "id": "S746",
        title_key: "Signal classification to detect evoked compound action potential features",
        AUTHORS: "Leonid M. Litvak; Joshua J. Nedrud; Janelle Blum; David Dinsmoor; Juan Manuel Montes Hincapie",
        YEAR: 2025,
        VENUE: "WIPO PatentScope / PCT publication",
        MODALITY: "SCS ECAP waveforms, stimulation artifacts and simulated ECAP response-model data",
        TASK: "ECAP/no-ECAP/noise classification, artifact separation and therapy-supporting signal interpretation",
        METHOD: "Growth-curve threshold labeling, clinically weighted samples, SVM/CNN classifiers and optional encoder-decoder pretraining",
        DATASET: "Claimed recorded and simulated ECAP waveform collections; no empirical cohort or public dataset is reported",
        PERFORMANCE: "Patent text states example classifier accuracy greater than 90%, without an auditable empirical evaluation protocol",
        CROSS_SUBJECT: None,
        relevance_key: 5,
        LIMITATIONS: "Patent claims and embodiments are prior art, not empirical evidence. No cohort, split, independent validation, calibration or public data are established. Simulated ECAP pretraining and artifact removal materially narrow novelty claims but do not include Drosophila or connectome-constrained transfer.",
        source_type_key: "патент",
        "identifiers": {
            "doi": None,
            "pmid": None,
            "arxiv_id": None,
            "patent_id": "WO2025224687A1",
            "dataset_id": None,
            "exact_url": "https://patents.google.com/patent/WO2025224687A1/en",
        },
        "provenance": {
            "import_source": "ecap-scs-prior-art-review-2026-09-24",
            "retrieved_at": DATE,
            "search_stream": "NS-08/NS-09/NS-10/NS-13",
            "query_or_seed": "ECAP neural network simulated data artifact classification patent",
            "iteration": 2,
        },
        "evidence": {
            "species": "Homo sapiens and simulated signals",
            "population": "SCS ECAP waveforms and simulated ECAP response-model data; no empirical cohort reported",
            "subject_domain": "mixed",
            "modalities": ["ecap", "simulation_state"],
            "sample_size": None,
            "target_construct": "technical_signal_quality",
            "target_label": "ECAP, no ECAP or noise; reconstructed waveform without stimulation artifact",
            "access_status": "open",
            "evidence_role": "context_only",
        },
        "validation": {
            "status": "verified_primary",
            "screening_status": "included_core",
            "full_text_status": "checked",
            "checked_at": DATE,
            "notes": "WIPO publication and claims reviewed. Patent disclosure is prior art, not empirical validation.",
            "split_unit": "not_reported",
            "cross_subject": "not_reported",
            "external_validation": "not_reported",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
            "exclusion_reason": None,
        },
        "risk_flags": [
            "patent_not_empirical_evidence",
            "synthetic_only",
            "ecap_not_pain_measure",
            "claim_not_supported",
        ],
        "relations": [],
    }
    record = migrate_record(record, checked_at=DATE)
    _set_resolution_locators(
        record,
        "WIPO publication WO2025224687A1, claims and description paragraphs [0007]-[0011], [0069]-[0077], [0085]-[0086]",
    )
    return record


def _update_evidence(evidence: dict[str, Any], records_by_id: dict[str, Any]) -> None:
    rows = evidence["rows"]
    by_source = {
        row["source_ids"][0]: row
        for row in rows
        if len(row.get("source_ids", [])) == 1
    }
    for source_id, spec in UPDATES.items():
        row = by_source[source_id]
        record = records_by_id[source_id]
        row.update(
            {
                "batch_id": "ecap-scs-review-2026-09-24",
                "claim": spec["claim"],
                "target_variable": record["evidence"]["target_label"],
                "population_or_data": record["evidence"]["population"] or "not available after primary-source search",
                "verified_evidence": spec["verified"],
                "limitations": record[LIMITATIONS],
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
    rows.append(
        {
            "batch_id": "ecap-scs-review-2026-09-24",
            "claim": "Patent WO2025224687A1 discloses simulated-data ECAP classification, growth-curve labeling and encoder-decoder artifact-removal pretraining.",
            "target_variable": "ECAP/no-ECAP/noise classification and artifact-separated waveform",
            "population_or_data": "Claimed simulated and recorded SCS ECAP waveforms; no empirical cohort reported",
            "source_ids": ["S746"],
            "verified_evidence": "The WIPO patent publication explicitly claims simulated ECAP training data and describes classifier and encoder-decoder embodiments.",
            "limitations": records_by_id["S746"][LIMITATIONS],
            "permitted_conclusion": "Treat as close technical prior art for synthetic ECAP and artifact-removal components, not as empirical performance or a Drosophila-to-SCS transfer analogue.",
            "locators": [
                {
                    "source_id": "S746",
                    "url": records_by_id["S746"]["identifiers"]["exact_url"],
                    "locator": "Claims and description paragraphs [0007]-[0011], [0069]-[0077], [0085]-[0086]",
                }
            ],
        }
    )
    evidence["meta"]["generated_at"] = DATE


def build_outputs(data_dir: Path = DATA) -> dict[str, dict[str, Any]]:
    records = load_json(data_dir / "records.json")
    existing = {record["id"] for record in records["sources"]}
    if "S746" in existing:
        raise ValueError("S746 already exists")
    found: set[str] = set()
    updated_sources: list[dict[str, Any]] = []
    for record in records["sources"]:
        if record["id"] in UPDATES:
            record = _update_record(record, UPDATES[record["id"]])
            found.add(record["id"])
        updated_sources.append(record)
    if found != set(UPDATES):
        raise ValueError(f"missing source IDs: {sorted(set(UPDATES) - found)}")
    patent_template = next(record for record in updated_sources if record["id"] == "S098")
    updated_sources.append(_new_patent(patent_template))
    updated_sources.sort(key=lambda source: int(source["id"][1:]))
    records["sources"] = updated_sources
    statuses = Counter(record["validation"]["status"] for record in updated_sources)
    aliases = load_json(data_dir / "aliases.json")
    records["meta"].update(
        {
            "records_count": len(updated_sources),
            "verified_primary_count": statuses["verified_primary"],
            "aliases_count": len(aliases["aliases"]),
            "updated_at": DATE,
        }
    )
    records_by_id = {record["id"]: record for record in updated_sources}

    evidence = load_json(data_dir / "evidence-matrix.json")
    _update_evidence(evidence, records_by_id)

    clusters = load_json(data_dir / "clusters.json")
    cluster = next(item for item in clusters["clusters"] if item["id"] == "C01")
    if "S746" not in cluster["состав_кластера"]:
        cluster["состав_кластера"].append("S746")
        cluster["состав_кластера"].sort(key=lambda source_id: int(source_id[1:]))
    cluster["записей"] = len(cluster["состав_кластера"])
    cluster["синтез"] = (
        "Кластер объединяет ML-детекцию ECAP, физическое формирование сигнала и "
        "патентный prior art по синтетическим ECAP, взвешиванию пороговых примеров и "
        "удалению стимуляционного артефакта. Патентные заявления не считаются эмпирической валидацией."
    )
    cluster["validation"]["checked_at"] = DATE
    cluster["content_review"]["checked_at"] = DATE
    clustered_ids = {
        source_id
        for item in clusters["clusters"]
        for source_id in item["состав_кластера"]
    }
    clusters["meta"].update(
        {
            "records_count": len(updated_sources),
            "cluster_references_count": sum(
                len(item["состав_кластера"]) for item in clusters["clusters"]
            ),
            "unique_clustered_records_count": len(clustered_ids),
            "unclustered_records_count": len(updated_sources) - len(clustered_ids),
            "updated_at": DATE,
        }
    )

    search = load_json(data_dir / "search-protocol.json")
    for stream_id in ("NS-08", "NS-09", "NS-10", "NS-13"):
        stream = next(item for item in search["search_streams"] if item["id"] == stream_id)
        if "S746" not in stream["source_ids"]:
            stream["source_ids"].append("S746")
        stream["status"] = "initial_pass_recorded"
    search["search_runs"] = [
        item for item in search["search_runs"] if item["id"] != "NS-RUN-2026-09-24-02"
    ]
    search["search_runs"].append(
        {
            "id": "NS-RUN-2026-09-24-02",
            "date": DATE,
            "queries": [
                "ECAP neural network simulated data artifact classification patent",
                "Using Neural Networks to Detect Evoked Compound Action Potentials SCS",
                "ECAP closed-loop SCS response prediction 2026",
            ],
            "primary_urls": [
                "https://patents.google.com/patent/WO2025224687A1/en",
                "https://pubmed.ncbi.nlm.nih.gov/40879389/",
                "https://www.sciencedirect.com/science/article/abs/pii/S1094715925006439",
                "https://assets.cureus.com/uploads/case_report/pdf/460390/20260202-302464-fuovtq.pdf",
                "https://jphv.ub.ac.id/index.php/jphv/article/view/306",
            ],
            "new_mechanism_classes": [
                "growth-curve-derived ECAP labels",
                "clinically weighted threshold samples",
                "encoder-decoder artifact-removal pretraining",
            ],
            "direct_drosophila_ecap_scs_analogue_found": False,
            "saturation": False,
        }
    )

    novelty = load_json(data_dir / "novelty-landscape.json")
    for variant in novelty["variants"]:
        if "S746" not in variant["closest_analogue_refs"]:
            variant["closest_analogue_refs"].append("S746")
        if "NS-13" not in variant["search_trace_ids"]:
            variant["search_trace_ids"].append("NS-13")
        variant["difference_from_analogues"] = (
            "Patent WO2025224687A1 already discloses simulated ECAP training data, "
            "growth-curve labeling and encoder-decoder artifact-removal pretraining. "
            "The remaining proposed distinction is the explicitly tested contribution of "
            "connectome-constrained Drosophila dynamics plus a separate physical ECAP operator; "
            "none of the cited analogues establishes that complete chain."
        )
    novelty["meta"]["generated_at"] = DATE

    validation_log = load_json(data_dir / "validation-log.json")
    searches = validation_log.setdefault("searches", [])
    searches[:] = [
        item for item in searches if item.get("search_id") != "ECAP-SCS-2026-09-24-01"
    ]
    searches.append(
        {
            "search_id": "ECAP-SCS-2026-09-24-01",
            "date": DATE,
            "stream": "ECAP detection, SCS response prediction, closed-loop evidence and patents",
            "query": "exact title/DOI followed by publisher, PubMed, Crossref and WIPO primary pages",
            "urls_reviewed": [
                UPDATES[source_id]["url"] for source_id in sorted(UPDATES)
            ]
            + [records_by_id["S746"]["identifiers"]["exact_url"]],
            "source_ids": sorted([*UPDATES, "S746"]),
            "decision": "three primary upgrades, two partial verifications, two terminal metadata/full-text-unavailable decisions, and one new patent prior-art record",
        }
    )
    validation_log["meta"]["checked_at"] = DATE

    audit = load_json(data_dir / "audit-report.json")
    audit["current_corpus"].update(
        {
            "canonical_sources": len(updated_sources),
            "validation_statuses": dict(sorted(statuses.items())),
        }
    )
    audit["meta"]["generated_at"] = DATE
    audit["ecap_scs_review"] = {
        "checked_at": DATE,
        "reviewed_source_ids": sorted(UPDATES),
        "added_source_ids": ["S746"],
        "finding": "synthetic ECAP classification and artifact-removal pretraining are disclosed in patent prior art; no Drosophila-to-ECAP/SCS direct analogue was found in this pass",
    }

    completeness = load_json(data_dir / "completeness-report.json")
    completeness.update(completeness_summary(updated_sources))
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
    with tempfile.TemporaryDirectory(prefix="research-ecap-scs-") as temporary:
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
        snapshot = snapshot_repository(DATA, label="pre-ecap-scs-review")
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
                "added": ["S746"],
                "snapshot": str(snapshot) if snapshot else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
