"""Candidate lifecycle: create, review and publish new source records."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..common.clock import utc_now
from ..common.errors import DataError
from ..common.jsonio import atomic_write_json, load_json
from ..registry.completeness import completeness_summary, migrate_record
from ..registry.layout import data_path
from ..registry.validation import LEGACY_FIELDS, validate_repository, validate_source_record
from .snapshots import snapshot_repository


def read_candidate_records(path: Path | str) -> list[dict[str, Any]]:
    path = Path(path).resolve()
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise DataError(f"cannot read candidate file {path}: {exc}") from exc
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict) and isinstance(payload.get("sources"), list):
        candidates = payload["sources"]
    elif isinstance(payload, dict):
        candidates = [payload]
    else:
        raise DataError("candidate JSON must be one source, an array, or {'sources': [...]}")
    if not candidates or any(not isinstance(item, dict) for item in candidates):
        raise DataError("candidate source list must contain at least one object")
    return candidates


def new_candidate(root: Path | str, title: str) -> dict[str, Any]:
    root = Path(root).resolve()
    if not title.strip():
        raise DataError("candidate title cannot be empty")
    template = load_json(root / "staging" / "source-record.template.json")
    records = load_json(data_path(root, "records.json")).get("sources", [])
    aliases = load_json(data_path(root, "aliases.json")).get("aliases", {})
    numeric_ids = [
        int(source_id[1:])
        for source_id in [*(record.get("id") for record in records), *aliases]
        if isinstance(source_id, str) and source_id[1:].isdigit()
    ]
    template["id"] = f"S{max(numeric_ids, default=0) + 1:03d}"
    template["название"] = title.strip()
    template["provenance"]["retrieved_at"] = utc_now().date().isoformat()
    template["validation"]["notes"] = "Generated candidate; requires primary-source review."
    return migrate_record(template, checked_at=utc_now().date().isoformat())


def _duplicate_key(record: dict[str, Any]) -> str:
    payload = {key: record.get(key) for key in LEGACY_FIELDS}
    payload["название"] = str(payload.get("название") or "").casefold().strip()
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _normalized_identifier(field: str, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().casefold()
    if field == "exact_url":
        normalized = normalized.rstrip("/")
    if field == "doi":
        normalized = normalized.removeprefix("https://doi.org/").removeprefix("doi:")
    return normalized


def review_candidates(root: Path | str, candidate_path: Path | str) -> dict[str, Any]:
    root = Path(root).resolve()
    schema = load_json(data_path(root, "source-record.schema.json"))
    vocab = load_json(data_path(root, "vocabularies.json"))
    records = load_json(data_path(root, "records.json")).get("sources", [])
    aliases = load_json(data_path(root, "aliases.json")).get("aliases", {})
    candidates = read_candidate_records(candidate_path)
    existing_ids = {record.get("id") for record in records} | set(aliases)
    existing_keys = {_duplicate_key(record): record.get("id") for record in records}
    identifier_fields = ("doi", "pmid", "arxiv_id", "patent_id", "dataset_id", "exact_url")
    existing_identifiers: dict[tuple[str, str], str] = {}
    for record in records:
        for field in identifier_fields:
            value = _normalized_identifier(field, record.get("identifiers", {}).get(field))
            if value:
                existing_identifiers[(field, value)] = record["id"]
    candidate_ids: set[str] = set()
    candidate_identifiers: dict[tuple[str, str], str] = {}
    errors: list[str] = []
    warnings: list[str] = []
    for candidate in candidates:
        errors.extend(validate_source_record(candidate, schema, vocab))
        source_id = candidate.get("id")
        if source_id in existing_ids:
            errors.append(f"{source_id}: id already exists as a canonical id or alias")
        if source_id in candidate_ids:
            errors.append(f"{source_id}: duplicate id in candidate batch")
        candidate_ids.add(source_id)
        duplicate_of = existing_keys.get(_duplicate_key(candidate))
        if duplicate_of:
            errors.append(f"{source_id}: exact duplicate of {duplicate_of}")
        title = str(candidate.get("название") or "").casefold().strip()
        same_titles = [
            record.get("id")
            for record in records
            if str(record.get("название") or "").casefold().strip() == title
        ]
        if same_titles and not duplicate_of:
            warnings.append(f"{source_id}: title also appears in {', '.join(same_titles)}")
        for field in identifier_fields:
            value = _normalized_identifier(field, candidate.get("identifiers", {}).get(field))
            if not value:
                continue
            existing_id = existing_identifiers.get((field, value))
            if existing_id:
                errors.append(f"{source_id}: {field} already belongs to {existing_id}")
            batch_id = candidate_identifiers.get((field, value))
            if batch_id:
                errors.append(f"{source_id}: {field} duplicates candidate {batch_id}")
            candidate_identifiers[(field, value)] = source_id
        provenance = candidate.get("provenance", {})
        if not provenance.get("retrieved_at"):
            warnings.append(f"{source_id}: provenance.retrieved_at is empty")
        if candidate.get("validation", {}).get("status") == "verified_primary":
            identifiers = candidate.get("identifiers", {})
            if not any(identifiers.get(key) for key in ("doi", "pmid", "exact_url")):
                errors.append(f"{source_id}: verified_primary requires DOI, PMID, or exact URL")
    return {
        "ok": not errors,
        "candidate_count": len(candidates),
        "candidate_ids": sorted(candidate_ids),
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "candidates": candidates,
    }


def publish_candidates(
    root: Path | str, candidate_path: Path | str, *, apply: bool = False
) -> dict[str, Any]:
    root = Path(root).resolve()
    current_report = validate_repository(root)
    if not current_report["ok"]:
        raise DataError("current repository is invalid; repair it before publishing")
    review = review_candidates(root, candidate_path)
    result = {key: value for key, value in review.items() if key != "candidates"}
    result["applied"] = False
    if not review["ok"] or not apply:
        return result

    snapshot = snapshot_repository(root, label="pre-publish")
    records_payload = load_json(data_path(root, "records.json"))
    clusters_payload = load_json(data_path(root, "clusters.json"))
    completeness_payload = load_json(data_path(root, "completeness-report.json"))
    records_payload = deepcopy(records_payload)
    clusters_payload = deepcopy(clusters_payload)
    records_payload["sources"].extend(deepcopy(review["candidates"]))
    records_payload["sources"].sort(key=lambda item: int(item["id"][1:]))
    record_meta = records_payload.setdefault("meta", {})
    record_meta["records_count"] = len(records_payload["sources"])
    record_meta["verified_primary_count"] = sum(
        item.get("validation", {}).get("status") == "verified_primary"
        for item in records_payload["sources"]
    )
    record_meta["unverified_count"] = sum(
        item.get("validation", {}).get("status") == "unverified"
        for item in records_payload["sources"]
    )
    record_meta["updated_at"] = utc_now().date().isoformat()

    new_ids = {item["id"] for item in review["candidates"]}
    unclustered = set(clusters_payload.get("unclustered_record_ids", [])) | new_ids
    clusters_payload["unclustered_record_ids"] = sorted(
        unclustered, key=lambda source_id: int(source_id[1:])
    )
    cluster_meta = clusters_payload.setdefault("meta", {})
    cluster_meta["records_count"] = len(records_payload["sources"])
    cluster_meta["unclustered_records_count"] = len(unclustered)
    cluster_meta["updated_at"] = utc_now().date().isoformat()

    summary = completeness_summary(records_payload["sources"])
    completeness_payload.update(summary)
    completeness_payload.setdefault("meta", {})["generated_at"] = utc_now().date().isoformat()

    atomic_write_json(data_path(root, "records.json"), records_payload)
    atomic_write_json(data_path(root, "clusters.json"), clusters_payload)
    atomic_write_json(data_path(root, "completeness-report.json"), completeness_payload)
    final_report = validate_repository(root)
    if not final_report["ok"]:
        raise DataError(
            "post-publish validation failed; restore working files from "
            f"{snapshot}: {'; '.join(final_report['errors'])}"
        )
    result.update({"applied": True, "snapshot": str(snapshot), "integrity": final_report})
    return result
