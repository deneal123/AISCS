"""Review closed-loop and digital-twin sources and add the primary rat study."""

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
    _set_resolution_locators,
    _update_record,
)
from service.completeness import completeness_summary, migrate_record
from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-24"

UPDATES: dict[str, dict[str, Any]] = {
    "S001": {
        "url": "https://www.nature.com/articles/s41928-025-01377-3",
        "fields": {
            MODALITY: "Publisher research briefing about rat neural recordings and ultrasound-powered spinal stimulation",
            TASK: "Contextual summary of an adaptive animal neuromodulation system",
            METHOD: "Nature Electronics Research Briefing summarizing DOI 10.1038/s41928-025-01374-6",
            DATASET: None,
            PERFORMANCE: None,
            CROSS_SUBJECT: None,
            LIMITATIONS: "This is a publisher Research Briefing, not the primary experiment. It confirms the system concept but must not be used for sample, split, metric or efficacy claims; those belong to S747.",
        },
        "evidence": {
            "species": "Rattus norvegicus",
            "population": None,
            "subject_domain": "animal_other",
            "modalities": ["neural_activity", "other"],
            "sample_size": None,
            "target_construct": "nociceptive_response",
            "target_label": "Publisher-described pain-severity classes mapped to stimulation levels",
            "access_status": "open",
            "evidence_role": "context_only",
        },
        "validation": {
            "status": "verified_primary",
            "screening_status": "included_context",
            "full_text_status": "checked",
            "split_unit": "not_applicable",
            "cross_subject": "not_applicable",
            "external_validation": "not_applicable",
            "calibration": "not_applicable",
            "uncertainty": "not_applicable",
        },
        "risk_flags": ["news_or_secondary_source", "animal_to_human_transfer_unvalidated"],
        "locator": "Nature Electronics Research Briefing, summary and Additional information",
        "claim": "The publisher briefing describes a wireless ultrasonic implant coupled to ML-based adaptive stimulation in animal models.",
        "verified": "The briefing identity and its explicit link to primary article DOI 10.1038/s41928-025-01374-6 were checked.",
        "permitted": "Use only as contextual publisher commentary and cite S747 for experimental design, metrics and limitations.",
    },
    "S284": {
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC11565243/",
        "pmid": "39554511",
        "fields": {
            MODALITY: "Implantable neural sensing, on-chip event-driven processing and closed-loop electrical stimulation",
            TASK: "Perspective on low-power neuromorphic closed-loop neuromodulation",
            METHOD: "Narrative perspective covering responsive neurostimulation, neuromorphic hardware and on-device learning",
            DATASET: None,
            PERFORMANCE: "No original empirical benchmark; the article summarizes literature and argues for more than three orders of magnitude data reduction in neuromorphic processing",
            CROSS_SUBJECT: "not_applicable: perspective",
            LIMITATIONS: "Perspective rather than an ECAP/SCS validation study. Most concrete examples concern brain stimulation and epilepsy; projected power, latency and learning advantages are not proof of chronic-pain or SCS outcome benefit.",
        },
        "evidence": {
            "species": "Homo sapiens and computational systems",
            "population": "Published responsive-neurostimulation systems and neuromorphic hardware literature",
            "subject_domain": "mixed",
            "modalities": ["neural_activity", "other"],
            "sample_size": None,
            "target_construct": "technical_signal_quality",
            "target_label": "Low-power on-device detection, learning and responsive stimulation",
            "access_status": "open",
            "evidence_role": "method_baseline",
        },
        "validation": {
            "status": "verified_primary",
            "full_text_status": "checked",
            "split_unit": "not_applicable",
            "cross_subject": "not_applicable",
            "external_validation": "not_applicable",
            "calibration": "not_applicable",
            "uncertainty": "not_applicable",
        },
        "risk_flags": ["claim_not_supported", "ecap_not_pain_measure"],
        "locator": "PMC11565243, Abstract; Challenges; Conclusions",
        "claim": "A perspective identifies on-chip low-power inference and learning as unresolved requirements for responsive implantable neuromodulation.",
        "verified": "The open full text confirms the technical scope and that it proposes a future architecture rather than validating SCS outcomes.",
        "permitted": "Use as engineering motivation for low-power closed-loop baselines, not as evidence for ECAP accuracy, pain measurement or clinical efficacy.",
    },
    "S285": {
        "url": "https://www.nature.com/articles/s44385-026-00076-8",
        "fields": {
            MODALITY: "Biophysical volume conduction, neural response, neural recording and surrogate digital-twin models",
            TASK: "Model-based design and optimization of neuroprosthetic interfaces",
            METHOD: "Narrative review of hybrid VC-to-neural-response models, reciprocal recording operators, acceleration and surrogate models",
            DATASET: "Published neural-interface modeling studies across peripheral nerve, spinal cord, retina and brain",
            PERFORMANCE: "No pooled performance metric; the review formalizes volume-conduction, neural-response and neural-transduction subproblems",
            CROSS_SUBJECT: "not_applicable: review",
            LIMITATIONS: "Review, not a validated patient-specific SCS twin. It states that neural-to-physiological transduction for analgesia remains open and that neural recruitment is not itself a pain measure.",
        },
        "evidence": {
            "species": "Homo sapiens, animal models and simulations",
            "population": "Published neuroprosthetic interface and digital-twin models",
            "subject_domain": "mixed",
            "modalities": ["simulation_state", "neural_activity", "other"],
            "sample_size": None,
            "target_construct": "technical_signal_quality",
            "target_label": "Electrical field, neural recruitment and recorded-signal prediction",
            "access_status": "open",
            "evidence_role": "method_baseline",
        },
        "validation": {
            "status": "verified_primary",
            "full_text_status": "checked",
            "split_unit": "not_applicable",
            "cross_subject": "not_applicable",
            "external_validation": "not_applicable",
            "calibration": "not_applicable",
            "uncertainty": "not_applicable",
        },
        "risk_flags": ["ecap_not_pain_measure", "claim_not_supported"],
        "locator": "Full text, Introduction; Hybrid modeling of neural stimulation; Hybrid modeling of neural recording; Neural transduction problem",
        "claim": "Hybrid neural-interface models require separate volume-conduction, neural-response and physiological-transduction components, with recording obtained through an explicit observation operator.",
        "verified": "The open review explicitly formalizes those components and identifies analgesic neural transduction as an open problem.",
        "permitted": "Use as the methodological basis for a separate physical ECAP observation model; do not claim a validated SCS digital twin or map recruitment directly to pain.",
    },
}


def _new_primary_rat_study(briefing: dict[str, Any]) -> dict[str, Any]:
    record = deepcopy(briefing)
    record["id"] = "S747"
    title_key = list(record)[1]
    record[title_key] = "A programmable and self-adaptive ultrasonic wireless implant for personalized chronic pain management"
    record[AUTHORS] = "Yushun Zeng; Chen Gong; Gengxi Lu; Jianxing Wu; Xiao Wan; Yang Yang; Jie Ji; Junhang Zhang; Runze Li; Yizhe Sun; Ziyuan Che; Chi-Feng Chang; Hsiao-Chuan Liu; Jiawen Chen; Qingqing He; Xin Sun; Ruitong Chen; Sina Khazaee Nejad; Xunan Liu; Deepthi S. Rajendran Nair; Laiming Jiang; Jun Chen; Qifa Zhou"
    record[YEAR] = 2025
    record[VENUE] = "Nature Electronics"
    record[MODALITY] = "Anterior-cingulate extracellular field activity, protective behavior and ultrasound-powered spinal electrical stimulation"
    record[TASK] = "Three-level noxious-stimulus classification coupled to adaptive spinal stimulation in freely moving rats"
    record[METHOD] = "ResNet-18 classification of rat neural recordings followed by programmable ultrasound-powered SCS and conditioned-place-aversion assessment"
    record[DATASET] = "Six male Long-Evans rats selected after spared-nerve injury; 5,770 signal entries with 5,570 training entries and 200 randomly separated test entries"
    record[PERFORMANCE] = "Overall three-class accuracy 94.8%; each class exceeded 90%; conditioned-place-aversion comparison n=6, P<0.0001"
    record[CROSS_SUBJECT] = "no: random signal-entry split; no held-out-animal evaluation is reported"
    record[LIMITATIONS] = "Animal-only experiment with six rats and a random entry-level split that can mix observations from the same animal across training and test. Labels are stimulus-linked nociceptive-response classes, not human subjective pain. The signal is not ECAP and there is no human SCS outcome validation."
    record["identifiers"] = {
        "doi": "10.1038/s41928-025-01374-6",
        "pmid": None,
        "arxiv_id": None,
        "patent_id": None,
        "dataset_id": None,
        "exact_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13095316/",
    }
    record["provenance"] = {
        "import_source": "closed-loop-model-review-2026-09-24",
        "retrieved_at": DATE,
        "search_stream": "NS-10/NS-12/NS-16",
        "query_or_seed": "primary article behind S001 Nature Electronics Research Briefing",
        "iteration": 2,
    }
    record["evidence"] = {
        "species": "Rattus norvegicus",
        "population": "Six male Long-Evans rats with spared-nerve-injury chronic-pain model",
        "subject_domain": "animal_other",
        "modalities": ["neural_activity", "behavior", "other"],
        "sample_size": 6,
        "target_construct": "nociceptive_response",
        "target_label": "Slight, moderate and extreme mechanical-stimulus response classes",
        "access_status": "open",
        "evidence_role": "method_baseline",
    }
    record["validation"] = {
        "status": "verified_primary",
        "screening_status": "included_core",
        "full_text_status": "checked",
        "checked_at": DATE,
        "notes": record[LIMITATIONS],
        "split_unit": "recording",
        "cross_subject": "no",
        "external_validation": "no",
        "calibration": "not_reported",
        "uncertainty": "yes",
        "exclusion_reason": None,
    }
    record["risk_flags"] = [
        "animal_to_human_transfer_unvalidated",
        "missing_cross_subject_validation",
        "ecap_not_pain_measure",
        "claim_not_supported",
    ]
    record["relations"] = []
    record = migrate_record(record, checked_at=DATE)
    _set_resolution_locators(
        record,
        "PMC13095316, Abstract; UIWI stimulator characteristics; Closed-loop chronic pain management; Methods: animal procedure and ML development",
    )
    return record


def build_outputs(data_dir: Path = DATA) -> dict[str, dict[str, Any]]:
    records = load_json(data_dir / "records.json")
    if any(record["id"] == "S747" for record in records["sources"]):
        raise ValueError("S747 already exists")
    found: set[str] = set()
    sources: list[dict[str, Any]] = []
    briefing: dict[str, Any] | None = None
    for record in records["sources"]:
        if record["id"] in UPDATES:
            record = _update_record(record, UPDATES[record["id"]])
            found.add(record["id"])
        if record["id"] == "S001":
            briefing = record
        sources.append(record)
    if found != set(UPDATES) or briefing is None:
        raise ValueError(f"missing source IDs: {sorted(set(UPDATES) - found)}")
    sources.append(_new_primary_rat_study(briefing))
    sources.sort(key=lambda source: int(source["id"][1:]))
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
        single_rows[source_id].update(
            {
                "batch_id": "closed-loop-model-review-2026-09-24",
                "claim": spec["claim"],
                "target_variable": source["evidence"]["target_label"],
                "population_or_data": source["evidence"]["population"] or "not applicable to this contextual source",
                "verified_evidence": spec["verified"],
                "limitations": source[LIMITATIONS],
                "permitted_conclusion": spec["permitted"],
                "locators": [{"source_id": source_id, "url": spec["url"], "locator": spec["locator"]}],
            }
        )
    evidence["rows"].append(
        {
            "batch_id": "closed-loop-model-review-2026-09-24",
            "claim": "A rat study couples neural-signal classification to adaptive spinal stimulation, but uses a random entry-level split and no held-out-animal test.",
            "target_variable": by_id["S747"]["evidence"]["target_label"],
            "population_or_data": by_id["S747"]["evidence"]["population"],
            "source_ids": ["S747"],
            "verified_evidence": by_id["S747"][PERFORMANCE],
            "limitations": by_id["S747"][LIMITATIONS],
            "permitted_conclusion": "Use as animal closed-loop prior art and a leakage-control warning; do not call the labels subjective pain or infer human/ECAP/SCS transfer.",
            "locators": [{"source_id": "S747", "url": by_id["S747"]["identifiers"]["exact_url"], "locator": "Abstract; Closed-loop chronic pain management; Methods: Data acquisition and ML model development"}],
        }
    )
    evidence["meta"]["generated_at"] = DATE

    clusters = load_json(data_dir / "clusters.json")
    cluster = next(item for item in clusters["clusters"] if item["id"] == "C20")
    cluster["состав_кластера"].append("S747")
    cluster["состав_кластера"].sort(key=lambda source_id: int(source_id[1:]))
    cluster["записей"] = len(cluster["состав_кластера"])
    cluster["синтез"] = "Кластер разделяет человеческие ECAP-controlled SCS reviews, вторичный Research Briefing S001 и первичный animal closed-loop experiment S747; эти уровни не являются взаимозаменяемыми."
    cluster["validation"]["checked_at"] = DATE
    cluster["content_review"]["checked_at"] = DATE
    clustered_ids = {source_id for item in clusters["clusters"] for source_id in item["состав_кластера"]}
    clusters["meta"].update(
        {
            "records_count": len(sources),
            "cluster_references_count": sum(len(item["состав_кластера"]) for item in clusters["clusters"]),
            "unique_clustered_records_count": len(clustered_ids),
            "unclustered_records_count": len(sources) - len(clustered_ids),
            "updated_at": DATE,
        }
    )

    search = load_json(data_dir / "search-protocol.json")
    for stream_id in ("NS-10", "NS-12", "NS-16"):
        stream = next(item for item in search["search_streams"] if item["id"] == stream_id)
        if "S747" not in stream["source_ids"]:
            stream["source_ids"].append("S747")
        stream["status"] = "initial_pass_recorded" if stream_id != "NS-16" else "second_pass_recorded"
    search["search_runs"].append(
        {
            "id": "NS-RUN-2026-09-24-03",
            "date": DATE,
            "queries": [
                "primary article behind ultrasound-induced wireless implantable stimulator adaptive pain management",
                "neuromorphic neuromodulation on-chip closed-loop review",
                "biophysical surrogate digital twin neural interface volume conduction recording",
            ],
            "primary_urls": [UPDATES["S001"]["url"], by_id["S747"]["identifiers"]["exact_url"], UPDATES["S284"]["url"], UPDATES["S285"]["url"]],
            "new_mechanism_classes": ["animal neural-classifier-to-SCS closed loop", "explicit VC-neural-response-recording-transduction decomposition"],
            "direct_drosophila_ecap_scs_analogue_found": False,
            "saturation": False,
        }
    )

    novelty = load_json(data_dir / "novelty-landscape.json")
    for variant in novelty["variants"]:
        if "S747" not in variant["closest_analogue_refs"]:
            variant["closest_analogue_refs"].append("S747")
        if "NS-12" not in variant["search_trace_ids"]:
            variant["search_trace_ids"].append("NS-12")
        variant["difference_from_analogues"] += " S747 additionally couples rat neural-response classification to adaptive SCS, but has no Drosophila connectome, physical ECAP operator, held-out-animal test or human validation."
    novelty["meta"]["generated_at"] = DATE

    validation_log = load_json(data_dir / "validation-log.json")
    validation_log.setdefault("searches", []).append(
        {
            "search_id": "CLOSED-LOOP-MODELS-2026-09-24-01",
            "date": DATE,
            "stream": "animal closed-loop neuromodulation, neuromorphic control and digital twins",
            "query": "exact title/DOI, primary full text, and source cited by publisher briefing",
            "urls_reviewed": [UPDATES["S001"]["url"], by_id["S747"]["identifiers"]["exact_url"], UPDATES["S284"]["url"], UPDATES["S285"]["url"]],
            "source_ids": ["S001", "S284", "S285", "S747"],
            "decision": "three metadata records upgraded from checked full text and the missing primary animal study added",
        }
    )
    validation_log["meta"]["checked_at"] = DATE

    audit = load_json(data_dir / "audit-report.json")
    audit["current_corpus"].update({"canonical_sources": len(sources), "validation_statuses": dict(sorted(statuses.items()))})
    audit["meta"]["generated_at"] = DATE
    audit["closed_loop_model_review"] = {
        "checked_at": DATE,
        "reviewed_source_ids": sorted(UPDATES),
        "added_source_ids": ["S747"],
        "finding": "rat neural-classifier-to-SCS closed-loop prior art exists, but it does not implement Drosophila connectome transfer, ECAP formation or human validation",
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
    with tempfile.TemporaryDirectory(prefix="research-closed-loop-") as temporary:
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
        snapshot = snapshot_repository(DATA, label="pre-closed-loop-model-review")
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
        report = validate_repository(DATA)
        if not report["ok"]:
            raise RuntimeError(f"restore {snapshot}: {'; '.join(report['errors'])}")
    print(json.dumps({"ok": True, "applied": args.apply, "reviewed": sorted(UPDATES), "added": ["S747"], "snapshot": str(snapshot) if snapshot else None}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
