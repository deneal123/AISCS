"""Review the open layered pain-assessment framework source S148."""

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
SOURCE_ID = "S148"
URL = "https://www.dovepress.com/rethinking-pain-assessment-subjective-scales-biomarkers-and-multimodal-peer-reviewed-fulltext-article-JPR"

SPEC: dict[str, Any] = {
    "url": URL,
    "pmid": "42454002",
    "fields": {
        MODALITY: "Self-report, behavioral and functional proxies, neurophysiology, imaging, biofluids, autonomic physiology, wearables and multimodal AI",
        TASK: "Clinically oriented narrative framework for selecting pain-assessment layers by task and population",
        METHOD: "Narrative review of PubMed, Web of Science and Embase through April 2026 with author-derived clinical-maturity synthesis",
        DATASET: "Previously published reviews, consensus statements and representative studies; no new dataset or formal systematic-review corpus",
        PERFORMANCE: "No pooled effect or model metric; the review explicitly requires task-specific effect size, reproducibility, external validation, interpretability and decision impact",
        CROSS_SUBJECT: "not_applicable: narrative review",
        LIMITATIONS: "This is a clinically oriented narrative review, not a registered systematic review or evidence grade. Author-derived maturity labels are synthesis judgments. It explicitly states that self-report, behavior, function and biosignals are related but non-interchangeable and that no universal objective pain marker exists.",
    },
    "evidence": {
        "species": "Homo sapiens",
        "population": "Heterogeneous experimental and clinical pain literature through April 2026",
        "subject_domain": "mixed",
        "modalities": ["eeg", "ecg", "eda", "emg", "bvp_ppg", "video_face", "movement_pose", "clinical_outcome", "other"],
        "sample_size": None,
        "target_construct": "self_reported_pain",
        "target_label": "Task-specific pain assessment across subjective, behavioral, functional and mechanistic layers",
        "access_status": "open",
        "evidence_role": "context_only",
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
    "locator": "Publisher full text, Abstract; Literature Search and Inclusion Principles; four-layer framework; Discussion; Conclusion",
    "claim": "A 2026 narrative review formalizes four non-interchangeable assessment layers and rejects a universal objective pain marker.",
    "verified": "The open publisher full text explicitly separates subjective experience, behavioral/functional proxies, mechanistic biosignals and multimodal integration and limits AI to task-specific decision support.",
    "permitted": "Use as a conceptual boundary and clinical-context source; do not treat its author-derived maturity labels as formal evidence grades or any biosignal as a replacement for self-report.",
}


def build_outputs(data_dir: Path = DATA) -> dict[str, dict[str, Any]]:
    records = load_json(data_dir / "records.json")
    found = False
    sources = []
    for record in records["sources"]:
        if record["id"] == SOURCE_ID:
            record = _update_record(record, SPEC)
            found = True
        sources.append(record)
    if not found:
        raise ValueError(f"missing source ID: {SOURCE_ID}")
    records["sources"] = sources
    statuses = Counter(source["validation"]["status"] for source in sources)
    records["meta"].update({"verified_primary_count": statuses["verified_primary"], "updated_at": DATE})
    source = next(item for item in sources if item["id"] == SOURCE_ID)

    evidence = load_json(data_dir / "evidence-matrix.json")
    row = next(item for item in evidence["rows"] if item.get("source_ids") == [SOURCE_ID])
    row.update(
        {
            "batch_id": "pain-framework-review-2026-09-24",
            "claim": SPEC["claim"],
            "target_variable": source["evidence"]["target_label"],
            "population_or_data": source["evidence"]["population"],
            "verified_evidence": SPEC["verified"],
            "limitations": source[LIMITATIONS],
            "permitted_conclusion": SPEC["permitted"],
            "locators": [{"source_id": SOURCE_ID, "url": URL, "locator": SPEC["locator"]}],
        }
    )
    evidence["meta"]["generated_at"] = DATE

    clusters = load_json(data_dir / "clusters.json")
    for cluster in clusters["clusters"]:
        representative = cluster.get("представитель")
        if representative and representative.get("id") == SOURCE_ID:
            cluster["представитель"] = deepcopy(source)
        if SOURCE_ID in cluster.get("состав_кластера", []):
            cluster["validation"]["checked_at"] = DATE
            cluster["content_review"]["checked_at"] = DATE
    clusters["meta"]["updated_at"] = DATE

    search = load_json(data_dir / "search-protocol.json")
    ns17 = next(item for item in search["search_streams"] if item["id"] == "NS-17")
    if SOURCE_ID not in ns17["source_ids"]:
        ns17["source_ids"].append(SOURCE_ID)
        ns17["source_ids"].sort(key=lambda source_id: int(source_id[1:]))
    search["search_runs"].append(
        {
            "id": "NS-RUN-2026-09-24-06",
            "date": DATE,
            "queries": ["pain assessment subjective scales biomarkers multimodal integration primary full text"],
            "primary_urls": [URL],
            "new_mechanism_classes": ["four-layer non-interchangeable pain-assessment framework"],
            "direct_drosophila_ecap_scs_analogue_found": False,
            "saturation": False,
        }
    )

    novelty = load_json(data_dir / "novelty-landscape.json")
    for variant in novelty["variants"]:
        if SOURCE_ID not in variant["closest_analogue_refs"]:
            variant["closest_analogue_refs"].append(SOURCE_ID)
        if "NS-17" not in variant["search_trace_ids"]:
            variant["search_trace_ids"].append("NS-17")
        suffix = " S148 independently requires non-interchangeable subjective, behavioral, functional and mechanistic layers, reinforcing that a fly observable or ECAP recruitment signal cannot be relabeled as subjective pain."
        if suffix not in variant["difference_from_analogues"]:
            variant["difference_from_analogues"] += suffix
    novelty["meta"]["generated_at"] = DATE

    validation_log = load_json(data_dir / "validation-log.json")
    validation_log.setdefault("searches", []).append(
        {
            "search_id": "PAIN-FRAMEWORK-2026-09-24-01",
            "date": DATE,
            "stream": "pain construct and multimodal-integration boundary",
            "query": "exact title and DOI followed by publisher full text",
            "urls_reviewed": [URL],
            "source_ids": [SOURCE_ID],
            "decision": "upgraded to verified primary with explicit non-interchangeability and no-universal-marker boundary",
        }
    )
    validation_log["meta"]["checked_at"] = DATE

    audit = load_json(data_dir / "audit-report.json")
    audit["current_corpus"]["validation_statuses"] = dict(sorted(statuses.items()))
    audit["meta"]["generated_at"] = DATE
    audit["pain_framework_review"] = {"checked_at": DATE, "reviewed_source_ids": [SOURCE_ID], "finding": "pain constructs and measurement layers must not be treated as interchangeable"}
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
    with tempfile.TemporaryDirectory(prefix="research-pain-framework-") as temporary:
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
        snapshot = snapshot_repository(DATA, label="pre-pain-framework-review")
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
        report = validate_repository(DATA)
        if not report["ok"]:
            raise RuntimeError(f"restore {snapshot}: {'; '.join(report['errors'])}")
    print(json.dumps({"ok": True, "applied": args.apply, "reviewed": [SOURCE_ID], "snapshot": str(snapshot) if snapshot else None}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
