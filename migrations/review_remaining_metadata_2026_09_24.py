"""Resolve the remaining accessible metadata-only records and add the ModMix journal version."""

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
    AUTHORS,
    CROSS_SUBJECT,
    DATASET,
    LIMITATIONS,
    METHOD,
    MODALITY,
    PERFORMANCE,
    TASK,
    VENUE,
    YEAR,
    _update_record,
)
from service.completeness import completeness_summary, migrate_record
from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-24"
BATCH_ID = "remaining-metadata-review-2026-09-24"

UPDATES: dict[str, dict[str, Any]] = {
    "S035": {
        "url": "https://link.springer.com/chapter/10.1007/978-3-031-88220-3_11",
        "fields": {
            MODALITY: None,
            TASK: "Multimodal pain-detection data augmentation",
            METHOD: "Randomized modality mixing (ModMix)",
            DATASET: "BioVid, as recorded in the conference metadata; experimental details unavailable from the accessible publisher preview",
            PERFORMANCE: None,
            CROSS_SUBJECT: None,
            LIMITATIONS: "Springer confirms the chapter identity, authors, pages 145-155 and conference context, but the chapter is subscription-only and its cohort, modalities, split and metrics could not be checked legally. A distinct open 2026 journal extension is retained as S748 rather than merged into this record.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": None,
            "subject_domain": "human_healthy",
            "modalities": [],
            "sample_size": None,
            "target_construct": "experimental_pain_class",
            "target_label": None,
            "access_status": "restricted",
            "evidence_role": "method_baseline",
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
        "risk_flags": ["metadata_only", "missing_cross_subject_validation"],
        "locator": "Springer proceedings page, table of contents, chapter 12, pages 145-155; subscription-content notice",
        "claim": "The ICPR workshop chapter introduced ModMix for multimodal pain detection.",
        "verified": "Publisher metadata confirms the chapter identity and placement; substantive method and result claims were not extracted from the later journal version.",
        "permitted": "Use only as bibliographic prior art for ModMix; cite S748 for the accessible journal-version evidence.",
    },
    "S071": {
        "url": "https://repository.essex.ac.uk/38532/1/YiyuanHan_Thesis_CSEE.pdf",
        "fields": {
            MODALITY: "62-channel scalp EEG; alpha-band phase functional connectivity",
            TASK: "Classification of controlled tonic thermal-pain and control conditions, including held-out-participant tests",
            METHOD: "CNN on alpha-phase functional connectivity with leave-one-participant-out, selective transfer and adversarial/partial-fine-tuning analyses",
            DATASET: "University of Essex controlled experiment: 43 recruited healthy adults, 36 analysed after exclusions",
            PERFORMANCE: "Table 5.7 reports 57.81% mean original leave-one-out accuracy and 69.56-69.75% maxima after cumulative-evidence aggregation; within-subject and subject-mixed values are not external generalization",
            CROSS_SUBJECT: "yes: leave-one-participant-out tests across 36 analysed participants",
            LIMITATIONS: "Single-site controlled acute tonic-heat experiment with 36 analysed healthy adults. The thesis itself reports materially weaker held-out-participant performance and unsuccessful selective transfer; no independent dataset, chronic-pain cohort, SCS cohort or clinical outcome validation is provided.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "36 analysed healthy adults (19 female; age 20-56) from 43 recruited participants",
            "subject_domain": "human_healthy",
            "modalities": ["eeg", "other"],
            "sample_size": 36,
            "target_construct": "experimental_pain_class",
            "target_label": "Hot, warm and resting-state experimental conditions with repeated unpleasantness VAS reports",
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
            "uncertainty": "not_reported",
        },
        "risk_flags": ["missing_cross_subject_validation"],
        "locator": "Doctoral thesis, Chapter 3 pp. 65-69; Table 5.7 p. 136; Chapter 5 conclusions pp. 145-146; Chapter 6",
        "claim": "EEG functional-connectivity models were evaluated with participant-held-out tests in a controlled tonic-heat experiment.",
        "verified": "The full thesis confirms the 36-participant cohort, experimental conditions, EEG acquisition, leave-one-participant-out protocol and the performance gap between mixed/within-participant and held-out-participant tests.",
        "permitted": "Use as evidence that participant-held-out EEG pain-condition classification is difficult; do not transfer the results to chronic pain, ECAP or SCS outcomes.",
    },
    "S074": {
        "url": "https://doi.org/10.1109/ICICNCT66124.2025.11232711",
        "doi": "10.1109/ICICNCT66124.2025.11232711",
        "fields": {
            MODALITY: None,
            TASK: "Pain-intensity assessment in sickle-cell disease",
            METHOD: "Claimed multimodal ensemble and LSTM framework; implementation not checked",
            DATASET: None,
            PERFORMANCE: None,
            CROSS_SUBJECT: None,
            LIMITATIONS: "Crossref and the official proceedings contents confirm the DOI, title, authors and page 362 start, but no accessible publisher full text was located. Cohort, labels, modalities, split and reported metrics remain unavailable and secondary-index summaries are not promoted to evidence.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": None,
            "subject_domain": "human_clinical",
            "modalities": [],
            "sample_size": None,
            "target_construct": "self_reported_pain",
            "target_label": None,
            "access_status": "restricted",
            "evidence_role": "method_baseline",
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
        "risk_flags": ["metadata_only", "claim_not_supported", "missing_cross_subject_validation"],
        "locator": "Crossref DOI record and ICICNCT 2025 proceedings table of contents, page 362; publisher full text unavailable",
        "claim": "A conference paper with this sickle-cell pain-assessment title and DOI exists.",
        "verified": "Only bibliographic identity and proceedings placement are verified from primary metadata.",
        "permitted": "Use as identity-level prior art only; do not cite its cohort, modalities, metrics or generalization.",
    },
    "S193": {
        "url": "https://hzo-py.github.io/publication/pain",
        "fields": {
            MODALITY: "Multiple clinical observation modalities; exact sensor list unavailable in the accessible abstract",
            TASK: "Regression of postoperative pain scores in children",
            METHOD: "Per-modality sample clustering, multiple expert regressors and confidence-based multimodal integration",
            DATASET: "Authors' postoperative-children multimodal pain database; cohort size and access terms unavailable in the accessible abstract",
            PERFORMANCE: "Author-hosted abstract reports MAE 1.03 and Pearson correlation 0.88",
            CROSS_SUBJECT: None,
            LIMITATIONS: "The author-hosted abstract confirms the mechanism and two headline metrics, but the IEEE full text is restricted. Cohort size, modalities, pain-score instrument, participant-level split, confidence construction and external validation were not independently checked.",
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "Postoperative children; cohort size unavailable in the accessible abstract",
            "subject_domain": "human_clinical",
            "modalities": ["other"],
            "sample_size": None,
            "target_construct": "self_reported_pain",
            "target_label": "Postoperative pain score; exact instrument unavailable in the accessible abstract",
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
        "risk_flags": ["metadata_only", "missing_cross_subject_validation"],
        "locator": "Author publication page, abstract and reported-results paragraph; IEEE DOI 10.1109/TAFFC.2025.3567307",
        "claim": "The paper proposes a confidence-integrated multi-expert model for postoperative pediatric pain-score regression.",
        "verified": "The author-hosted abstract confirms the method outline and reports MAE 1.03 and PCC 0.88.",
        "permitted": "Use the method and abstract-level metrics with an explicit abstract-only caveat; do not assert participant-level or external generalization.",
    },
    "S228": {
        "url": "https://www.dsu.edu.in/images/Engineering/CSE-dept/Newsletter/CsOct-Dec_2025.pdf",
        "fields": {
            MODALITY: None,
            TASK: "Generic federated healthcare diagnostics",
            METHOD: None,
            DATASET: None,
            PERFORMANCE: None,
            CROSS_SUBJECT: None,
            LIMITATIONS: "The only primary institutional item located is a departmental newsletter reporting that a presentation occurred at ICIMMI-2025. No paper, DOI, abstract, dataset or auditable 98.21% result was found. The item does not address pain, Drosophila, ECAP or SCS and is excluded as irrelevant and unverifiable for this evidence base.",
        },
        "evidence": {
            "species": None,
            "population": None,
            "subject_domain": "not_applicable",
            "modalities": [],
            "sample_size": None,
            "target_construct": "not_applicable",
            "target_label": None,
            "access_status": "unavailable_after_search",
            "evidence_role": "context_only",
        },
        "validation": {
            "status": "rejected",
            "screening_status": "excluded_irrelevant",
            "full_text_status": "unavailable",
            "split_unit": "not_applicable",
            "cross_subject": "not_applicable",
            "external_validation": "not_applicable",
            "calibration": "not_applicable",
            "uncertainty": "not_applicable",
            "exclusion_reason": "irrelevant",
        },
        "risk_flags": ["claim_not_supported", "metadata_only"],
        "locator": "Dayananda Sagar University CSE EDUINSIDE newsletter, Oct-Dec 2025, Faculty Achievements entry for ICIMMI-2025",
        "claim": "The institutional newsletter confirms only that a presentation with this title occurred.",
        "verified": "Title, presenters, conference name and presentation dates were checked; no scientific content or metric was recoverable.",
        "permitted": "Do not use this record as scientific evidence or prior art for the dissertation mechanism.",
    },
    "S229": {
        "url": "https://pubmed.ncbi.nlm.nih.gov/39356594/",
        "pmid": "39356594",
        "fields": {
            MODALITY: "Event-driven SNN benchmark inputs (MNIST, NMNIST and DVS-Gesture)",
            TASK: "Energy-efficient on-chip supervised SNN learning",
            METHOD: "28-nm multi-core event-driven processor with neuromodulator-formulated local/global online learning",
            DATASET: "MNIST, NMNIST and DVS-Gesture",
            PERFORMANCE: "PubMed abstract reports 99.2%, 98.2% and 94.3% benchmark accuracy; 328 GOPS/51 GSOPS peak throughput and 5.3 pJ/SOP",
            CROSS_SUBJECT: "not_applicable",
            LIMITATIONS: "Here 'neuromodulation' denotes a learning rule in neuromorphic hardware, not therapeutic neuromodulation. The paper contains no pain construct, biological Drosophila model, ECAP signal or SCS task; abstract-level hardware results are context only.",
        },
        "evidence": {
            "species": "not_applicable",
            "population": "Neuromorphic hardware benchmarks, not biological participants",
            "subject_domain": "simulation",
            "modalities": ["simulation_state", "other"],
            "sample_size": None,
            "target_construct": "technical_signal_quality",
            "target_label": "Benchmark classification accuracy, throughput and energy efficiency",
            "access_status": "restricted",
            "evidence_role": "context_only",
        },
        "validation": {
            "status": "partially_verified",
            "full_text_status": "metadata_only",
            "split_unit": "not_applicable",
            "cross_subject": "not_applicable",
            "external_validation": "not_reported",
            "calibration": "not_applicable",
            "uncertainty": "not_reported",
        },
        "risk_flags": ["metadata_only"],
        "locator": "PubMed PMID 39356594, bibliographic record and abstract",
        "claim": "EPOC demonstrates an event-driven neuromorphic learning processor on standard vision benchmarks.",
        "verified": "PubMed confirms the identity, hardware architecture, benchmark names, reported accuracies, throughput and energy figure at abstract level.",
        "permitted": "Use only as neuromorphic-hardware context; do not treat it as SCS, ECAP or pain evidence.",
    },
}


def _new_modmix_journal(template: dict[str, Any]) -> dict[str, Any]:
    title_key = list(template)[1]
    source_type_key = "тип_источника"
    relevance_key = "релевантность"
    record = {
        "id": "S748",
        title_key: "Randomized Modality Mixing with Patchwise RBF Networks for Robust Multimodal Pain Recognition",
        AUTHORS: "Mehmet Erdal; Sascha Gruss; Steffen Walter; Friedhelm Schwenker",
        YEAR: 2026,
        VENUE: "Computers",
        MODALITY: "Multimodal physiological signals; exact channels require full-text recheck",
        TASK: "Robust multimodal experimental-pain recognition under limited training data",
        METHOD: "Randomized modality mixing plus patchwise radial-basis-function networks and ensemble aggregation",
        DATASET: "X-ITE and BioVid; approximately 30% of each dataset used for training according to the publisher abstract",
        PERFORMANCE: "Publisher abstract reports significant gains for a subset of participants and similar or slightly better mean accuracy than random forest and SVM, without headline numeric values",
        CROSS_SUBJECT: "not_reported in the accessible publisher abstract",
        relevance_key: 4,
        LIMITATIONS: "The official open-access issue page and Crossref abstract were checked, but automated full-PDF retrieval was blocked during this audit. The accessible abstract does not establish a participant-independent split, external dataset validation, calibration or transfer to clinical pain, ECAP or SCS.",
        source_type_key: template[source_type_key],
        "identifiers": {
            "doi": "10.3390/computers15020127",
            "pmid": None,
            "arxiv_id": None,
            "patent_id": None,
            "dataset_id": None,
            "exact_url": "https://www.mdpi.com/2073-431X/15/2/127",
        },
        "provenance": {
            "import_source": BATCH_ID,
            "retrieved_at": DATE,
            "search_stream": "NS-06/NS-16",
            "query_or_seed": "exact ModMix title author version search",
            "iteration": 2,
        },
        "evidence": {
            "species": "Homo sapiens",
            "population": "Participants represented in X-ITE and BioVid; counts unavailable in the accessible abstract",
            "subject_domain": "human_healthy",
            "modalities": ["other"],
            "sample_size": None,
            "target_construct": "experimental_pain_class",
            "target_label": "Experimental pain-recognition labels in X-ITE and BioVid",
            "access_status": "open",
            "evidence_role": "method_baseline",
        },
        "validation": {
            "status": "partially_verified",
            "screening_status": "included_core",
            "full_text_status": "metadata_only",
            "checked_at": DATE,
            "notes": "Official issue-page and Crossref abstract checked; full-text methods and split remain to be manually rechecked.",
            "split_unit": "unavailable_after_search",
            "cross_subject": "not_reported",
            "external_validation": "not_reported",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
            "exclusion_reason": None,
        },
        "relations": [
            {
                "type": "version_of",
                "target_id": "S035",
                "external_id": None,
                "note": "Expanded open-access journal treatment of the ModMix method introduced in the ICPR workshop chapter.",
            }
        ],
        "risk_flags": ["metadata_only", "missing_cross_subject_validation"],
    }
    return migrate_record(record, checked_at=DATE)


def build_outputs(data_dir: Path = DATA) -> dict[str, dict[str, Any]]:
    records = load_json(data_dir / "records.json")
    existing = {record["id"] for record in records["sources"]}
    if "S748" in existing:
        raise ValueError("S748 already exists")
    found: set[str] = set()
    sources: list[dict[str, Any]] = []
    for record in records["sources"]:
        if record["id"] in UPDATES:
            record = _update_record(record, UPDATES[record["id"]])
            if UPDATES[record["id"]].get("doi"):
                record["identifiers"]["doi"] = UPDATES[record["id"]]["doi"]
                record = migrate_record(record, checked_at=DATE)
            found.add(record["id"])
        sources.append(record)
    if found != set(UPDATES):
        raise ValueError(f"missing source IDs: {sorted(set(UPDATES) - found)}")
    sources.append(_new_modmix_journal(next(record for record in sources if record["id"] == "S035")))
    sources.sort(key=lambda source: int(source["id"][1:]))
    records["sources"] = sources
    statuses = Counter(source["validation"]["status"] for source in sources)
    aliases = load_json(data_dir / "aliases.json")
    records["meta"].update({
        "records_count": len(sources),
        "verified_primary_count": statuses["verified_primary"],
        "aliases_count": len(aliases["aliases"]),
        "updated_at": DATE,
    })
    by_id = {source["id"]: source for source in sources}

    evidence = load_json(data_dir / "evidence-matrix.json")
    rows = {row["source_ids"][0]: row for row in evidence["rows"] if len(row.get("source_ids", [])) == 1}
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
        if source_id in rows:
            rows[source_id].update(payload)
        else:
            evidence["rows"].append(payload)
    evidence["rows"].append({
        "batch_id": BATCH_ID,
        "claim": "The 2026 ModMix journal version evaluates randomized modality mixing and patchwise RBF networks on X-ITE and BioVid under limited training data.",
        "target_variable": "experimental pain-recognition class",
        "population_or_data": "X-ITE and BioVid participants; exact counts and split unavailable in the accessible abstract",
        "source_ids": ["S748"],
        "verified_evidence": "Official MDPI issue-page and Crossref abstract confirm the method, datasets and approximately 30% training-data condition.",
        "limitations": by_id["S748"][LIMITATIONS],
        "permitted_conclusion": "Use as synthetic/augmentation prior art only; do not claim participant-independent or clinical generalization.",
        "locators": [{"source_id": "S748", "url": by_id["S748"]["identifiers"]["exact_url"], "locator": "publisher issue-page abstract and Crossref abstract"}],
    })
    evidence["meta"]["generated_at"] = DATE

    clusters = load_json(data_dir / "clusters.json")
    for cluster in clusters["clusters"]:
        representative = cluster.get("представитель")
        if representative and representative.get("id") in UPDATES:
            cluster["представитель"] = deepcopy(by_id[representative["id"]])
        members = cluster.get("состав_кластера", [])
        if cluster["id"] in {"C08", "C34"} and "S748" not in members:
            members.append("S748")
            members.sort(key=lambda source_id: int(source_id[1:]))
            cluster["записей"] = len(members)
        if any(source_id in UPDATES for source_id in members) or "S748" in members:
            cluster["validation"]["checked_at"] = DATE
            cluster["content_review"]["checked_at"] = DATE
    refs = [source_id for cluster in clusters["clusters"] for source_id in cluster["состав_кластера"]]
    counts = Counter(refs)
    clusters["multiple_membership"] = {source_id: count for source_id, count in sorted(counts.items()) if count > 1}
    clusters["multiple_membership_rationale"]["S748"] = {
        "cluster_ids": ["C08", "C34"],
        "reason": "The journal article is both a synthetic-data/augmentation method and a direct ModMix-family source; dual membership is navigational, not independent evidence.",
    }
    clusters["meta"].update({
        "records_count": len(sources),
        "cluster_references_count": len(refs),
        "unique_clustered_records_count": len(set(refs)),
        "unclustered_records_count": len(sources) - len(set(refs)),
        "multiple_membership_records_count": len(clusters["multiple_membership"]),
        "updated_at": DATE,
    })

    search = load_json(data_dir / "search-protocol.json")
    for stream_id in ("NS-06", "NS-16"):
        stream = next(item for item in search["search_streams"] if item["id"] == stream_id)
        if "S748" not in stream["source_ids"]:
            stream["source_ids"].append("S748")
            stream["source_ids"].sort(key=lambda source_id: int(source_id[1:]))
        stream["status"] = "second_pass_recorded"
    search["search_runs"].append({
        "id": "NS-RUN-2026-09-24-08",
        "date": DATE,
        "queries": [
            "exact title and DOI search for remaining verified_metadata records",
            "ModMix author and version search",
            "institutional full-text search for EEG pain transfer thesis",
        ],
        "primary_urls": [spec["url"] for spec in UPDATES.values()] + [by_id["S748"]["identifiers"]["exact_url"]],
        "new_mechanism_classes": ["ModMix patchwise RBF journal extension"],
        "direct_drosophila_ecap_scs_analogue_found": False,
        "saturation": False,
    })

    novelty = load_json(data_dir / "novelty-landscape.json")
    for variant in novelty["variants"]:
        if "S748" not in variant["closest_analogue_refs"]:
            variant["closest_analogue_refs"].append("S748")
        for stream_id in ("NS-06", "NS-16"):
            if stream_id not in variant["search_trace_ids"]:
                variant["search_trace_ids"].append(stream_id)
        suffix = " The open 2026 ModMix extension (S748) strengthens prior art for physiological-modality augmentation under limited data, but it does not provide Drosophila-derived representations, a physical ECAP operator, or an SCS task."
        if suffix not in variant["difference_from_analogues"]:
            variant["difference_from_analogues"] += suffix
    novelty["meta"]["generated_at"] = DATE

    validation_log = load_json(data_dir / "validation-log.json")
    validation_log.setdefault("searches", []).append({
        "search_id": "REMAINING-METADATA-2026-09-24-01",
        "date": DATE,
        "stream": "terminal resolution of accessible verified-metadata sources and ModMix version discovery",
        "query": "exact title, DOI, author repository, institutional repository and publisher full text",
        "urls_reviewed": [spec["url"] for spec in UPDATES.values()] + [by_id["S748"]["identifiers"]["exact_url"]],
        "source_ids": sorted(UPDATES) + ["S748"],
        "decision": "one full thesis verified, two abstract-level records retained as partial, one irrelevant unsupported item rejected, two paywalled records terminally documented, and one new journal version added",
    })
    validation_log["meta"]["checked_at"] = DATE

    audit = load_json(data_dir / "audit-report.json")
    audit["current_corpus"].update({"canonical_sources": len(sources), "validation_statuses": dict(sorted(statuses.items()))})
    audit["meta"]["generated_at"] = DATE
    audit["remaining_metadata_review"] = {
        "checked_at": DATE,
        "reviewed_source_ids": sorted(UPDATES),
        "added_source_ids": ["S748"],
        "finding": "all remaining metadata-only records now have either source-specific terminal access boundaries or an upgraded evidence status",
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
    with tempfile.TemporaryDirectory(prefix="research-remaining-metadata-") as temporary:
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
        snapshot = snapshot_repository(DATA, label="pre-remaining-metadata-review")
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
        report = validate_repository(DATA)
        if not report["ok"]:
            raise RuntimeError(f"restore {snapshot}: {'; '.join(report['errors'])}")
    print(json.dumps({"ok": True, "applied": args.apply, "reviewed": sorted(UPDATES), "added": ["S748"], "snapshot": str(snapshot) if snapshot else None}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
