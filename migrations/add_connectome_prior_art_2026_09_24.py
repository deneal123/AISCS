"""Add connectome-control prior art discovered during the novelty audit."""

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


def _record(
    *,
    source_id: str,
    title: str,
    authors: str,
    year: int,
    venue: str,
    source_type: str,
    url: str,
    doi: str | None = None,
    pmid: str | None = None,
    arxiv_id: str | None = None,
    species: str,
    population: str,
    subject_domain: str,
    modalities: list[str],
    method: str,
    dataset: str,
    result: str,
    limitations: str,
    relations: list[dict[str, Any]] | None = None,
    risk_flags: list[str] | None = None,
) -> dict[str, Any]:
    record = {
        "id": source_id,
        "название": title,
        "авторы": authors,
        "год": year,
        "издание": venue,
        "модальность": ", ".join(modalities),
        "задача": "Оценка идентифицируемости и вклада структурных ограничений коннектома",
        "метод": method,
        "датасет": dataset,
        "производительность": result,
        "кросс_субъект": "not_applicable",
        "релевантность": 5,
        "ограничения": limitations,
        "тип_источника": source_type,
        "identifiers": {
            "doi": doi,
            "pmid": pmid,
            "arxiv_id": arxiv_id,
            "patent_id": None,
            "dataset_id": None,
            "exact_url": url,
        },
        "provenance": {
            "import_source": "connectome-prior-art-refresh-2026-09-24",
            "retrieved_at": DATE,
            "search_stream": "NS-02/NS-05/NS-16",
            "query_or_seed": "connectome-constrained dynamics transfer random graph controls",
            "iteration": 2,
        },
        "evidence": {
            "species": species,
            "population": population,
            "subject_domain": subject_domain,
            "modalities": modalities,
            "sample_size": None,
            "target_construct": "technical_signal_quality",
            "target_label": "connectome-constrained neural dynamics",
            "access_status": "open",
            "evidence_role": "method_baseline",
        },
        "validation": {
            "status": "verified_primary",
            "screening_status": "included_core",
            "full_text_status": "checked",
            "checked_at": DATE,
            "split_unit": "not_applicable",
            "cross_subject": "not_applicable",
            "external_validation": "not_reported",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
            "exclusion_reason": None,
            "notes": limitations,
        },
        "relations": relations or [],
        "risk_flags": risk_flags or ["animal_to_human_transfer_unvalidated"],
    }
    return migrate_record(record, checked_at=DATE)


def new_records() -> list[dict[str, Any]]:
    return [
        _record(
            source_id="S741",
            title="Topological Sensitivity in Connectome-Constrained Neural Networks",
            authors="Nalin Dhiman",
            year=2026,
            venue="arXiv",
            source_type="препринт",
            url="https://arxiv.org/abs/2604.04033",
            arxiv_id="2604.04033",
            species="Drosophila melanogaster",
            population="flyvis Drosophila visual-system connectome model",
            subject_domain="simulation",
            modalities=["connectome", "neural_activity", "simulation_state"],
            method="Shared-from-scratch initialization with naive and degree-preserving rewired graph nulls",
            dataset="flyvis connectome-constrained model and a five-sample degree-preserving null ensemble",
            result="The apparent topology advantage largely disappears under shared initialization and degree-preserving controls.",
            limitations="Preprint and visual-system task only. It establishes a mandatory control against initialization and graph-null confounding, not a result for nociception, ECAP, or SCS.",
            risk_flags=[
                "preprint",
                "synthetic_only",
                "animal_to_human_transfer_unvalidated",
                "future_or_recent_record_requires_recheck",
            ],
        ),
        _record(
            source_id="S742",
            title="Exploiting Large Neuroimaging Datasets to Create Connectome-Constrained Approaches for more Robust, Efficient, and Adaptable Artificial Intelligence",
            authors="Erik C. Johnson; Brian S. Robinson; Gautam K. Vallabha; Justin Joyce; Jordan K. Matelsky; Raphael Norman-Tenazas; Isaac Western; Marisel Villafañe-Delgado; Martha Cervantes; Michael S. Robinette; Arun V. Reddy; Lindsey Kitchell; Patricia K. Rivlin; Elizabeth P. Reilly; Nathan Drenkow; Matthew J. Roos; I-Jeng Wang; Brock A. Wester; William R. Gray-Roncal; Joan A. Hoffmann",
            year=2023,
            venue="arXiv",
            source_type="препринт",
            url="https://arxiv.org/abs/2305.17300",
            arxiv_id="2305.17300",
            species="Drosophila melanogaster and mammalian neuroimaging",
            population="connectome-derived machine-learning case studies",
            subject_domain="mixed",
            modalities=["connectome", "simulation_state", "other"],
            method="Motif discovery, connectome-informed circuit modelling, generative replay, and connectivity-constrained ML",
            dataset="Hemibrain and other large neuroimaging/connectomics datasets",
            result="Documents prior transfer of connectome-derived structure into unrelated AI tasks, including Drosophila-inspired generative replay.",
            limitations="A perspective and case-study synthesis; it does not address nociception, physical ECAP formation, or SCS.",
            risk_flags=["preprint", "animal_to_human_transfer_unvalidated"],
        ),
        _record(
            source_id="S743",
            title="Prediction of neural activity in connectome-constrained recurrent networks",
            authors="Manuel Beiran; Ashok Litwin-Kumar",
            year=2025,
            venue="Nature Neuroscience",
            source_type="метод",
            url="https://pmc.ncbi.nlm.nih.gov/articles/PMC12648571/",
            doi="10.1038/s41593-025-02080-4",
            species="Drosophila melanogaster and Danio rerio",
            population="simulated larval and adult Drosophila circuits and larval zebrafish circuit",
            subject_domain="mixed",
            modalities=["connectome", "neural_activity", "simulation_state"],
            method="Teacher-student recurrent networks constrained by empirical circuit connectivity",
            dataset="Drosophila larval premotor, adult central-complex, and zebrafish oculomotor connectomes",
            result="Characterizes when partial neural recordings and connectome constraints identify unrecorded activity and parameters.",
            limitations="Circuit-dynamics identifiability result; no pain construct, human ECAP, spinal-cord equivalence, or SCS transfer.",
            relations=[
                {
                    "type": "version_of",
                    "target_id": None,
                    "external_id": "doi:10.1101/2024.02.22.581667",
                    "note": "Journal version of the 2024 bioRxiv preprint.",
                }
            ],
        ),
        _record(
            source_id="S744",
            title="Connectome-constrained networks predict neural activity across the fly visual system",
            authors="Janne K. Lappalainen; Fabian D. Tschopp; Sridhama Prakhya; Mason McGill; Aljoscha Nern; Kazunori Shinomiya; Shin-ya Takemura; Eyal Gruntman; Jakob H. Macke; Srinivas C. Turaga",
            year=2024,
            venue="Nature",
            source_type="метод",
            url="https://www.nature.com/articles/s41586-024-07939-3",
            doi="10.1038/s41586-024-07939-3",
            species="Drosophila melanogaster",
            population="adult fly visual-system cell types and connectome",
            subject_domain="drosophila_adult",
            modalities=["connectome", "neural_activity"],
            method="Connectome-constrained deep mechanistic network fitted to published neural responses",
            dataset="adult Drosophila visual-system connectome and compiled activity measurements",
            result="Predicts neural responses across 64 visual-system cell types and tests connectome-derived constraints.",
            limitations="Visual computation, not nociception; successful within-species functional prediction does not establish cross-species ECAP/SCS transfer.",
            relations=[
                {
                    "type": "version_of",
                    "target_id": None,
                    "external_id": "doi:10.1101/2023.05.02.539144",
                    "note": "Journal version of the 2023 bioRxiv preprint.",
                }
            ],
        ),
        _record(
            source_id="S745",
            title="Connectome-Constrained Latent Variable Models of Whole-Brain Neural Activity",
            authors="Lu Mi; Richard Xu; Sridhama Prakhya; Albert Lin; Nir Shavit; Aravinthan D. T. Samuel; Srinivas C. Turaga",
            year=2022,
            venue="International Conference on Learning Representations (ICLR)",
            source_type="метод",
            url="https://openreview.net/forum?id=CJzi3dRlJE-",
            species="Caenorhabditis elegans",
            population="21 immobilized animals with 170 identified head neurons",
            subject_domain="animal_other",
            modalities=["connectome", "neural_activity"],
            method="Connectome-constrained latent variable model with sparsity and synapse-count constraints",
            dataset="whole-brain calcium activity from 170 neurons across 21 C. elegans individuals",
            result="Compares nine model variants with dense, sparse, total-count, connectome-sparsity, and connectome-count constraints.",
            limitations="Different organism and sensory task; relevant as a model-design and ablation precedent only.",
        ),
    ]


def _replace_controls(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace(
            "random-connectome",
            "degree-preserving rewired-connectome ensemble with shared initialization",
        ).replace(
            "randomized-connectome",
            "degree-preserving rewired-connectome ensemble with shared initialization",
        ).replace(
            "randomized controls",
            "degree-preserving rewired-connectome controls with shared initialization",
        )
    if isinstance(value, list):
        return [_replace_controls(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace_controls(item) for key, item in value.items()}
    return value


def _completeness(records: list[dict[str, Any]]) -> dict[str, Any]:
    current = load_json(DATA / "completeness-report.json")
    current.update(completeness_summary(records))
    current["meta"]["generated_at"] = DATE
    return current


def build_outputs(data_dir: Path = DATA) -> dict[str, dict[str, Any]]:
    records = load_json(data_dir / "records.json")
    additions = new_records()
    existing_ids = {source["id"] for source in records["sources"]}
    if existing_ids & {source["id"] for source in additions}:
        raise ValueError("one or more prior-art IDs already exist")
    records["sources"].extend(additions)
    records["sources"].sort(key=lambda source: int(source["id"][1:]))
    records["meta"].update(
        {
            "records_count": len(records["sources"]),
            "verified_primary_count": sum(
                source["validation"]["status"] == "verified_primary"
                for source in records["sources"]
            ),
            "updated_at": DATE,
        }
    )

    clusters = load_json(data_dir / "clusters.json")
    cluster_map = {cluster["id"]: cluster for cluster in clusters["clusters"]}
    for cluster_id in ("C18", "C45"):
        cluster = cluster_map[cluster_id]
        cluster["состав_кластера"] = list(
            dict.fromkeys(cluster["состав_кластера"] + [source["id"] for source in additions])
        )
        cluster["записей"] = len(cluster["состав_кластера"])
        cluster["синтез"] = (
            f"Тематическая проекция «{cluster['тема']}» содержит "
            f"{cluster['записей']} канонических источников. Кластер служит навигации; "
            "научные выводы разрешаются только через evidence matrix и первичные локаторы."
        )
    refs = [
        source_id
        for cluster in clusters["clusters"]
        for source_id in cluster["состав_кластера"]
    ]
    counts = Counter(refs)
    clusters["multiple_membership"] = {
        source_id: count for source_id, count in sorted(counts.items()) if count > 1
    }
    for source in additions:
        clusters["multiple_membership_rationale"][source["id"]] = {
            "cluster_ids": ["C18", "C45"],
            "reason": "The source is both general connectome methodology and a computational connectome-model baseline; dual membership is navigational, not independent evidence.",
        }
    clusters["meta"].update(
        {
            "records_count": len(records["sources"]),
            "cluster_references_count": len(refs),
            "unique_clustered_records_count": len(set(refs)),
            "unclustered_records_count": len(clusters["unclustered_record_ids"]),
            "multiple_membership_records_count": len(clusters["multiple_membership"]),
            "updated_at": DATE,
        }
    )

    evidence = load_json(data_dir / "evidence-matrix.json")
    evidence["rows"].extend(
        [
            {
                "batch_id": "connectome-prior-art-refresh-2026-09-24",
                "claim": source["производительность"],
                "target_variable": "connectome constraint contribution",
                "population_or_data": source["evidence"]["population"],
                "source_ids": [source["id"]],
                "verified_evidence": f"Primary full text checked at {source['identifiers']['exact_url']}.",
                "limitations": source["ограничения"],
                "permitted_conclusion": "Use as connectome-model prior art and control-design evidence only.",
                "locators": [
                    {
                        "source_id": source["id"],
                        "url": source["identifiers"]["exact_url"],
                        "locator": "abstract, methods, experiments, and limitations/discussion",
                    }
                ],
            }
            for source in additions
        ]
    )
    evidence["meta"]["generated_at"] = DATE

    search = load_json(data_dir / "search-protocol.json")
    stream_map = {stream["id"]: stream for stream in search["search_streams"]}
    stream_map["NS-02"]["source_ids"] = list(
        dict.fromkeys(stream_map["NS-02"]["source_ids"] + ["S741", "S743", "S744", "S745"])
    )
    stream_map["NS-05"]["source_ids"] = ["S742", "S743", "S744", "S745"]
    stream_map["NS-05"]["status"] = "second_pass_recorded"
    stream_map["NS-16"]["source_ids"] = ["S741", "S742", "S743", "S744", "S745"]
    stream_map["NS-16"]["status"] = "second_pass_recorded"
    search.setdefault("search_runs", []).append(
        {
            "id": "NS-RUN-2026-09-24-01",
            "date": DATE,
            "queries": [
                "Drosophila connectome constrained ECAP spinal cord stimulation representation transfer",
                "connectome-constrained neural dynamics transfer learning ECAP SCS",
                "connectome-constrained random graph controls initialization",
            ],
            "primary_urls": [source["identifiers"]["exact_url"] for source in additions],
            "new_mechanism_classes": [
                "degree-preserving graph null with shared initialization",
                "partial-observation identifiability in connectome-constrained RNNs",
                "connectome-to-unrelated-AI-task transfer precedent",
            ],
            "direct_drosophila_ecap_scs_analogue_found": False,
            "saturation": False,
        }
    )
    search["meta"]["cutoff"] = DATE

    novelty = _replace_controls(load_json(data_dir / "novelty-landscape.json"))
    novelty["meta"]["cutoff"] = DATE
    for variant in novelty["variants"]:
        variant["closest_analogue_refs"] = list(
            dict.fromkeys(
                variant["closest_analogue_refs"] + ["S741", "S743", "S744"]
            )
        )
        variant["search_trace_ids"] = list(
            dict.fromkeys(
                variant["search_trace_ids"] + ["NS-02", "NS-05", "NS-16"]
            )
        )
        variant["prior_art_cutoff"] = DATE
    concept = _replace_controls(load_json(data_dir / "dissertation-concept.json"))
    concept["novelty_claims"][1]["source_refs"] = list(
        dict.fromkeys(concept["novelty_claims"][1]["source_refs"] + ["S741", "S743", "S744"])
    )

    audit = load_json(data_dir / "audit-report.json")
    statuses = Counter(source["validation"]["status"] for source in records["sources"])
    audit["current_corpus"].update(
        {
            "canonical_sources": len(records["sources"]),
            "validation_statuses": dict(sorted(statuses.items())),
        }
    )
    audit["meta"]["generated_at"] = DATE
    audit["connectome_prior_art_refresh"] = {
        "checked_at": DATE,
        "added_source_ids": [source["id"] for source in additions],
        "control_design_change": "replace naive random-connectome control with degree-preserving rewired ensembles trained from shared initialization",
        "direct_drosophila_ecap_scs_analogue_found": False,
        "search_saturated": False,
    }

    validation_log = load_json(data_dir / "validation-log.json")
    validation_log.setdefault("searches", []).append(
        {
            "search_id": "NS-2026-09-24-01",
            "date": DATE,
            "stream": "connectome constraints, transfer, and null-model confounding",
            "query": "Drosophila connectome constrained dynamics transfer random graph controls",
            "urls_reviewed": [source["identifiers"]["exact_url"] for source in additions],
            "source_ids": [source["id"] for source in additions],
            "decision": "included_core_prior_art",
        }
    )
    validation_log["meta"]["checked_at"] = DATE

    return {
        "records.json": records,
        "clusters.json": clusters,
        "evidence-matrix.json": evidence,
        "search-protocol.json": search,
        "novelty-landscape.json": novelty,
        "dissertation-concept.json": concept,
        "audit-report.json": audit,
        "validation-log.json": validation_log,
        "completeness-report.json": _completeness(records["sources"]),
    }


def validate_outputs(outputs: dict[str, dict[str, Any]], data_dir: Path = DATA) -> None:
    with tempfile.TemporaryDirectory(prefix="research-prior-art-") as temporary:
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
        snapshot = snapshot_repository(DATA, label="pre-connectome-prior-art-refresh")
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
    print(
        json.dumps(
            {
                "ok": True,
                "applied": args.apply,
                "added": [source["id"] for source in new_records()],
                "records": len(outputs["records.json"]["sources"]),
                "snapshot": str(snapshot) if snapshot else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
