"""Remove canonical records that share a stable identifier with a stronger record."""

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

from service.completeness import completeness_summary
from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-24"
MERGES = {"S002": "S105", "S062": "S029", "S238": "S162"}


def _replace(value: Any) -> Any:
    if isinstance(value, str):
        return MERGES.get(value, value)
    if isinstance(value, list):
        replaced = [_replace(item) for item in value]
        if all(isinstance(item, str) for item in replaced):
            return list(dict.fromkeys(replaced))
        return replaced
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            mapped_key = MERGES.get(key, key)
            mapped_value = _replace(item)
            if mapped_key not in result:
                result[mapped_key] = mapped_value
        return result
    return value


def _completeness(records: list[dict[str, Any]]) -> dict[str, Any]:
    report = completeness_summary(records)
    return {
        "meta": {
            "schema_version": "1.0.0",
            "generated_at": DATE,
            "records_schema_version": "2.0.0",
            "gate": "G0_REVISE",
        },
        **report,
        "policy": {
            "forbidden": [
                "unknown",
                "empty string",
                "TODO",
                "TBD",
                "Не указано",
                "unexplained null",
            ],
            "terminal_states": [
                "reported",
                "not_reported",
                "not_applicable",
                "unavailable_after_search",
            ],
            "structural_null_exceptions": [
                "resolved.value for terminal states",
                "mutually exclusive relation target_id/external_id",
            ],
        },
    }


def build_outputs(data_dir: Path = DATA) -> dict[str, dict[str, Any]]:
    records = load_json(data_dir / "records.json")
    aliases = load_json(data_dir / "aliases.json")
    clusters = load_json(data_dir / "clusters.json")
    evidence = load_json(data_dir / "evidence-matrix.json")
    contract = load_json(data_dir / "scientific-contract.json")
    novelty = load_json(data_dir / "novelty-landscape.json")
    concept = load_json(data_dir / "dissertation-concept.json")
    search = load_json(data_dir / "search-protocol.json")
    resources = load_json(data_dir / "ST.json")
    audit = load_json(data_dir / "audit-report.json")
    validation_log = load_json(data_dir / "validation-log.json")

    source_by_id = {source["id"]: source for source in records["sources"]}
    missing = (set(MERGES) | set(MERGES.values())) - set(source_by_id)
    if missing:
        raise ValueError(f"deduplication sources are missing: {sorted(missing)}")
    for alias_id, canonical_id in MERGES.items():
        alias_doi = source_by_id[alias_id]["identifiers"].get("doi")
        canonical_doi = source_by_id[canonical_id]["identifiers"].get("doi")
        if not alias_doi or alias_doi.casefold() != str(canonical_doi).casefold():
            raise ValueError(f"DOI mismatch for {alias_id} -> {canonical_id}")

    records["sources"] = [
        source for source in records["sources"] if source["id"] not in MERGES
    ]
    records["meta"]["records_count"] = len(records["sources"])
    records["meta"]["updated_at"] = DATE
    canonical_by_id = {source["id"]: source for source in records["sources"]}

    alias_map = aliases["aliases"]
    for entry in alias_map.values():
        entry["canonical_id"] = MERGES.get(entry["canonical_id"], entry["canonical_id"])
    for alias_id, canonical_id in MERGES.items():
        alias_map[alias_id] = {
            "canonical_id": canonical_id,
            "reason": "same DOI and title; stronger verified_primary record retained",
        }
    aliases["aliases"] = dict(sorted(alias_map.items()))
    aliases["meta"]["aliases_count"] = len(alias_map)
    aliases["meta"]["updated_at"] = DATE

    clusters = _replace(clusters)
    refs: list[str] = []
    for cluster in clusters["clusters"]:
        members = list(dict.fromkeys(cluster["состав_кластера"]))
        cluster["состав_кластера"] = members
        cluster["записей"] = len(members)
        representative_id = cluster["представитель"]["id"]
        cluster["представитель"] = deepcopy(canonical_by_id[representative_id])
        refs.extend(members)
    referenced = set(refs)
    canonical_ids = set(canonical_by_id)
    clusters["unclustered_record_ids"] = sorted(canonical_ids - referenced)
    clusters["multiple_membership"] = {
        source_id: count
        for source_id, count in sorted(Counter(refs).items())
        if count > 1
    }
    clusters["unclustered_decisions"] = {
        source_id: decision
        for source_id, decision in clusters.get("unclustered_decisions", {}).items()
        if source_id in clusters["unclustered_record_ids"]
    }
    clusters["multiple_membership_rationale"] = {
        source_id: rationale
        for source_id, rationale in clusters.get("multiple_membership_rationale", {}).items()
        if source_id in clusters["multiple_membership"]
    }
    cluster_meta = clusters["meta"]
    cluster_meta.update(
        {
            "records_count": len(canonical_ids),
            "cluster_references_count": len(refs),
            "unique_clustered_records_count": len(referenced),
            "unclustered_records_count": len(canonical_ids - referenced),
            "multiple_membership_records_count": len(clusters["multiple_membership"]),
            "updated_at": DATE,
        }
    )

    evidence = _replace(evidence)
    contract = _replace(contract)
    novelty = _replace(novelty)
    concept = _replace(concept)
    search = _replace(search)
    resources = _replace(resources)

    current = audit["current_corpus"]
    statuses = Counter(source["validation"]["status"] for source in records["sources"])
    current["canonical_sources"] = len(records["sources"])
    current["aliases"] = len(alias_map)
    current["validation_statuses"] = dict(sorted(statuses.items()))
    audit["meta"]["generated_at"] = DATE
    audit["canonical_identifier_deduplication"] = {
        "checked_at": DATE,
        "merged_aliases": MERGES,
        "policy": "one canonical record per normalized DOI; historical IDs resolve through aliases",
    }

    validation_log.setdefault("decisions", []).append(
        {
            "decision_id": "DEDUP-2026-09-24-01",
            "date": DATE,
            "decision": "canonical_identifier_merge",
            "aliases": MERGES,
            "evidence": "Each pair has an identical normalized DOI and exact title; the retained record has the stronger verified_primary extraction.",
        }
    )
    validation_log["meta"]["checked_at"] = DATE

    return {
        "records.json": records,
        "aliases.json": aliases,
        "clusters.json": clusters,
        "evidence-matrix.json": evidence,
        "scientific-contract.json": contract,
        "novelty-landscape.json": novelty,
        "dissertation-concept.json": concept,
        "search-protocol.json": search,
        "ST.json": resources,
        "audit-report.json": audit,
        "validation-log.json": validation_log,
        "completeness-report.json": _completeness(records["sources"]),
    }


def validate_outputs(outputs: dict[str, dict[str, Any]], data_dir: Path = DATA) -> None:
    with tempfile.TemporaryDirectory(prefix="research-dedup-") as temporary:
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
    if args.apply:
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
    result = {
        "ok": True,
        "applied": args.apply,
        "merges": MERGES,
        "records": len(outputs["records.json"]["sources"]),
        "aliases": len(outputs["aliases.json"]["aliases"]),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
