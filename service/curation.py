"""Batch curation workflow for relevance-ranked source records."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

from .core import DataError, load_json
from .integrity import validate_repository
from .pipeline import atomic_write_json, snapshot_repository

CURATION_RELATIVE = Path("curation") / "relevance-5"
DECISIONS = {
    "verified_primary",
    "verified_metadata",
    "partially_verified",
    "rejected",
    "alias",
}
FIRST_BATCH = [
    "S149",
    "S210",
    "S224",
    "S256",
    "S304",
    "S380",
    "S039",
    "S056",
    "S089",
    "S118",
    "S132",
    "S178",
    "S225",
    "S258",
    "S353",
    "S366",
    "S407",
    "S036",
    "S053",
    "S085",
    "S128",
]
VERSION_FAMILIES = [
    ["S004", "S080", "S125", "S146", "S226", "S257"],
    ["S005", "S101"],
    ["S006", "S104"],
    ["S007", "S103", "S265"],
    ["S003", "S059"],
    ["S033", "S047"],
    ["S037", "S054", "S141", "S205"],
    ["S040", "S055", "S120", "S130", "S142", "S180"],
    ["S044", "S057", "S081", "S117", "S126", "S145", "S263"],
    ["S069", "S171"],
    ["S070", "S112", "S147", "S163", "S172"],
    ["S072", "S114", "S174"],
    ["S078", "S124", "S139", "S202", "S349", "S364", "S401"],
    ["S079", "S123", "S290", "S300", "S324", "S339"],
    ["S082", "S127", "S143", "S207", "S264", "S374"],
    ["S086", "S129"],
    ["S088", "S119", "S131", "S179"],
    ["S148", "S194"],
    ["S140", "S158", "S203", "S217", "S270"],
    ["S164"],
    ["S195"],
    ["S236", "S277"],
    ["S237", "S278"],
    ["S238", "S351", "S362", "S402"],
    ["S239", "S275"],
    ["S243", "S276"],
    ["S284", "S297", "S321", "S336"],
    ["S285", "S298", "S322", "S337"],
    ["S289", "S299", "S323", "S338"],
    ["S356", "S358", "S403"],
    ["S357", "S359", "S404"],
    ["S360", "S408"],
    ["S361", "S409"],
]


def _numeric(source_id: str) -> int:
    return int(source_id[1:])


def _curation_relative(relevance: int) -> Path:
    return Path("curation") / f"relevance-{relevance}"


def _families(root: Path, eligible: set[str]) -> list[list[str]]:
    audit = load_json(root / "audit-report.json")
    raw_groups = audit.get("records", {}).get("pending_semantic_duplicate_groups", [])
    parent = {source_id: source_id for source_id in eligible}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for group in raw_groups:
        members = [item for item in group if item in eligible]
        for member in members[1:]:
            union(members[0], member)
    for group in VERSION_FAMILIES:
        members = [item for item in group if item in eligible]
        for member in members[1:]:
            union(members[0], member)
    result: dict[str, list[str]] = {}
    for source_id in eligible:
        result.setdefault(find(source_id), []).append(source_id)
    return [sorted(group, key=_numeric) for group in result.values()]


def _priority(record: dict[str, Any]) -> tuple[int, int, int]:
    title = str(record.get("название") or "").casefold()
    source_type = record.get("тип_источника")
    year = record.get("год") or 0
    if year == 2026 and any(marker in title for marker in ("final", "extended")):
        tier = 0
    elif source_type in {"патент", "применение"} or any(
        marker in title for marker in ("ecap", "scs", "spinal cord")
    ):
        tier = 1
    elif source_type in {"кросс_субъект", "метод", "XAI"}:
        tier = 2
    else:
        tier = 3
    return (tier, -year, _numeric(record["id"]))


def build_queue(
    root: Path | str,
    *,
    relevance: int = 5,
    status: str = "unverified",
    batch_size: int = 20,
) -> dict[str, Any]:
    root = Path(root).resolve()
    if batch_size < 1:
        raise DataError("batch-size must be positive")
    records = load_json(root / "records.json").get("sources", [])
    by_id = {record["id"]: record for record in records}
    eligible = {
        source_id
        for source_id, record in by_id.items()
        if record.get("релевантность") == relevance
        and record.get("validation", {}).get("status") == status
    }
    groups = _families(root, eligible)
    first = [source_id for source_id in FIRST_BATCH if source_id in eligible]
    consumed = set(first)
    remaining = [group for group in groups if not set(group) & consumed]
    remaining.sort(key=lambda group: min(_priority(by_id[item]) for item in group))
    batches: list[list[str]] = [first] if first else []
    for family in remaining:
        if not batches or len(batches[-1]) + len(family) > batch_size:
            batches.append([])
        batches[-1].extend(family)
    curation_dir = root / _curation_relative(relevance)
    batch_dir = curation_dir / "batches"
    batch_dir.mkdir(parents=True, exist_ok=True)
    manifests: list[dict[str, Any]] = []
    validation_log = load_json(root / "validation-log.json")
    applied_batches = validation_log.get("meta", {}).get("applied_batches", [])
    if relevance == 5:
        applied_for_scope = [item for item in applied_batches if item.startswith("batch-")]
        start_index = len(applied_for_scope) + 1
        batch_prefix = "batch"
    else:
        applied_for_scope = [
            item for item in applied_batches if item.startswith(f"r{relevance}-batch-")
        ]
        start_index = len(applied_for_scope) + 1
        batch_prefix = f"r{relevance}-batch"
    if not eligible and applied_for_scope:
        completed_manifests = []
        for batch_id in applied_for_scope:
            path = batch_dir / f"{batch_id}.json"
            if not path.is_file():
                raise DataError(f"applied review batch is missing: {path}")
            source_ids = load_json(path).get("source_ids", [])
            completed_manifests.append(
                {"batch_id": batch_id, "source_ids": source_ids, "path": str(path)}
            )
        queue = {
            "meta": {
                "version": "1.0.0",
                "generated_at": date.today().isoformat(),
                "relevance": relevance,
                "status": "complete",
                "batch_size_target": batch_size,
                "source_count": sum(len(item["source_ids"]) for item in completed_manifests),
                "batch_count": len(completed_manifests),
                "remaining_unverified_count": 0,
            },
            "batches": completed_manifests,
        }
        atomic_write_json(curation_dir / "queue.json", queue)
        return queue
    for index, source_ids in enumerate(batches, start=start_index):
        batch_id = f"{batch_prefix}-{index:03d}"
        manifest = {
            "meta": {
                "batch_id": batch_id,
                "schema_version": "1.2.0",
                "created_at": date.today().isoformat(),
                "scope": f"relevance={relevance}; status={status}",
                "status": "awaiting_review",
            },
            "source_ids": source_ids,
            "records": [
                {
                    "id": source_id,
                    "title": by_id[source_id]["название"],
                    "year": by_id[source_id].get("год"),
                    "source_type": by_id[source_id].get("тип_источника"),
                }
                for source_id in source_ids
            ],
            "decisions": [],
        }
        path = batch_dir / f"{batch_id}.json"
        existing_status = None
        if path.exists():
            existing_status = load_json(path).get("meta", {}).get("status")
        if not path.exists() or existing_status == "awaiting_review":
            atomic_write_json(path, manifest)
        manifests.append({"batch_id": batch_id, "source_ids": source_ids, "path": str(path)})
    queue = {
        "meta": {
            "version": "1.0.0",
            "generated_at": date.today().isoformat(),
            "relevance": relevance,
            "status": status,
            "batch_size_target": batch_size,
            "source_count": len(eligible),
            "batch_count": len(manifests),
        },
        "batches": manifests,
    }
    atomic_write_json(curation_dir / "queue.json", queue)
    return queue


def resolve_batch(root: Path, batch: Path | str) -> Path:
    candidate = Path(batch)
    if candidate.is_file():
        return candidate.resolve()
    name = candidate.name
    if not name.endswith(".json"):
        name += ".json"
    candidates = list((root / "curation").glob(f"relevance-*/batches/{name}"))
    if len(candidates) > 1:
        raise DataError(f"review batch is ambiguous; pass an explicit path: {batch}")
    if not candidates:
        raise DataError(f"review batch not found: {batch}")
    return candidates[0].resolve()


def review_check(root: Path | str, batch: Path | str) -> dict[str, Any]:
    root = Path(root).resolve()
    path = resolve_batch(root, batch)
    payload = load_json(path)
    records = load_json(root / "records.json").get("sources", [])
    canonical = {record["id"]: record for record in records}
    aliases = load_json(root / "aliases.json").get("aliases", {})
    manifest_ids = payload.get("source_ids", [])
    decisions = payload.get("decisions", [])
    errors: list[str] = []
    warnings: list[str] = []
    decision_ids = [item.get("source_id") for item in decisions if isinstance(item, dict)]
    if set(decision_ids) != set(manifest_ids) or len(decision_ids) != len(manifest_ids):
        errors.append("decisions must cover every manifest source exactly once")
    for decision in decisions:
        source_id = decision.get("source_id")
        outcome = decision.get("decision")
        if source_id not in canonical and source_id not in aliases:
            errors.append(f"{source_id}: not a canonical record or alias")
            continue
        if outcome not in DECISIONS:
            errors.append(f"{source_id}: unsupported decision {outcome!r}")
        searches = decision.get("searches")
        if not isinstance(searches, list) or not searches:
            errors.append(f"{source_id}: at least one documented search is required")
        elif any(not search.get("url") or not search.get("query") for search in searches):
            errors.append(f"{source_id}: each search requires query and URL")
        if outcome == "alias":
            target = decision.get("canonical_id")
            if not target or target == source_id:
                errors.append(f"{source_id}: alias requires another canonical_id")
            elif target not in canonical:
                errors.append(f"{source_id}: alias target {target} is not canonical")
        if outcome in {"verified_primary", "verified_metadata", "partially_verified"}:
            updates = decision.get("updates", {})
            identifiers = updates.get("identifiers", {})
            if not any(
                identifiers.get(key)
                for key in ("doi", "pmid", "arxiv_id", "patent_id", "exact_url")
            ):
                errors.append(f"{source_id}: verified decision requires a stable identifier")
        if outcome == "rejected" and not decision.get("exclusion_reason"):
            errors.append(f"{source_id}: rejected decision requires exclusion_reason")
        claims = decision.get("claims", [])
        if not isinstance(claims, list):
            errors.append(f"{source_id}: claims must be an array")
        if outcome == "verified_metadata":
            warnings.append(f"{source_id}: content claims remain unverified (metadata only)")
    return {
        "ok": not errors,
        "batch_id": payload.get("meta", {}).get("batch_id"),
        "path": str(path),
        "source_count": len(manifest_ids),
        "decision_count": len(decisions),
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
    }


def _deep_update(target: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = deepcopy(value)


def _rebuild_cluster_indexes(clusters: dict[str, Any], records: list[dict[str, Any]]) -> None:
    by_id = {record["id"]: record for record in records}
    canonical_ids = set(by_id)
    refs: list[str] = []
    active: list[dict[str, Any]] = []
    retired = clusters.setdefault("retired_clusters", [])
    retired_ids = {item.get("id") for item in retired}
    for cluster in clusters.get("clusters", []):
        members = [item for item in cluster.get("состав_кластера", []) if item in canonical_ids]
        if not members:
            if cluster.get("id") not in retired_ids:
                retired.append(
                    {
                        "id": cluster.get("id"),
                        "тема": cluster.get("тема"),
                        "reason": "all_members_became_aliases_during_curation",
                        "original_member_ids": cluster.get("состав_кластера", []),
                    }
                )
            continue
        cluster["состав_кластера"] = members
        cluster["записей"] = len(members)
        representative_id = (cluster.get("представитель") or {}).get("id")
        if representative_id not in members:
            representative_id = sorted(members, key=_numeric)[0]
        cluster["представитель"] = deepcopy(by_id[representative_id])
        refs.extend(members)
        active.append(cluster)
    clusters["clusters"] = active
    referenced = set(refs)
    clusters["unclustered_record_ids"] = sorted(canonical_ids - referenced, key=_numeric)
    clusters["multiple_membership"] = {
        key: count for key, count in sorted(Counter(refs).items()) if count > 1
    }
    meta = clusters.setdefault("meta", {})
    meta.update(
        {
            "schema_version": "1.2.0",
            "records_count": len(records),
            "clusters_count": len(active),
            "retired_clusters_count": len(retired),
            "cluster_references_count": len(refs),
            "unique_clustered_records_count": len(referenced),
            "unclustered_records_count": len(canonical_ids - referenced),
            "multiple_membership_records_count": sum(count > 1 for count in Counter(refs).values()),
            "updated_at": date.today().isoformat(),
        }
    )


def _status_screening(outcome: str, exclusion_reason: str | None) -> str:
    if outcome == "rejected":
        return {
            "duplicate": "excluded_duplicate",
            "irrelevant": "excluded_irrelevant",
        }.get(exclusion_reason, "excluded_unverifiable")
    return "included_core"


def review_apply(root: Path | str, batch: Path | str, *, apply: bool = False) -> dict[str, Any]:
    root = Path(root).resolve()
    check = review_check(root, batch)
    result = dict(check)
    result["applied"] = False
    if not check["ok"] or not apply:
        return result
    path = Path(check["path"])
    payload = load_json(path)
    batch_id = str(payload.get("meta", {}).get("batch_id"))
    validation_log = load_json(root / "validation-log.json")
    applied_batches = validation_log.get("meta", {}).get("applied_batches", [])
    if batch_id in applied_batches:
        result.update({"ok": True, "already_applied": True})
        return result

    current = validate_repository(root)
    if not current["ok"]:
        raise DataError("current repository is invalid; repair before applying a review")
    snapshot = snapshot_repository(root, label=f"pre-{batch_id}")
    names = [
        "records.json",
        "aliases.json",
        "clusters.json",
        "validation-log.json",
        "audit-report.json",
        "evidence-matrix.json",
    ]
    originals = {name: (root / name).read_bytes() for name in names}
    try:
        records_payload = load_json(root / "records.json")
        aliases_payload = load_json(root / "aliases.json")
        clusters_payload = load_json(root / "clusters.json")
        audit_payload = load_json(root / "audit-report.json")
        matrix_payload = load_json(root / "evidence-matrix.json")
        records = records_payload.get("sources", [])
        by_id = {record["id"]: record for record in records}
        aliases = aliases_payload.setdefault("aliases", {})
        removed: set[str] = set()
        for decision in payload["decisions"]:
            source_id = decision["source_id"]
            outcome = decision["decision"]
            if outcome == "alias":
                canonical_id = decision["canonical_id"]
                for existing in aliases.values():
                    if isinstance(existing, dict) and existing.get("canonical_id") == source_id:
                        existing["canonical_id"] = canonical_id
                        existing["reason"] = (
                            str(existing.get("reason") or "legacy_alias")
                            + "; canonical retargeted after reviewed merge"
                        )
                aliases[source_id] = {
                    "canonical_id": canonical_id,
                    "reason": decision.get("reason", "confirmed_same_source"),
                    "validated_at": date.today().isoformat(),
                }
                removed.add(source_id)
                continue
            record = by_id[source_id]
            _deep_update(record, decision.get("updates", {}))
            for field in decision.get("clear_fields", []):
                if field in record:
                    record[field] = None
            validation = record["validation"]
            validation.update(
                {
                    "status": outcome,
                    "screening_status": _status_screening(
                        outcome, decision.get("exclusion_reason")
                    ),
                    "checked_at": decision.get("checked_at", date.today().isoformat()),
                    "exclusion_reason": decision.get("exclusion_reason"),
                    "notes": decision.get("notes"),
                }
            )
            if outcome == "verified_primary":
                validation["full_text_status"] = decision.get("full_text_status", "checked")
            elif outcome == "verified_metadata":
                validation["full_text_status"] = "metadata_only"
            elif outcome == "partially_verified":
                validation["full_text_status"] = decision.get("full_text_status", "metadata_only")
            else:
                validation["full_text_status"] = decision.get("full_text_status", "unavailable")
                record["risk_flags"] = sorted(
                    set(record.get("risk_flags", [])) | {"claim_not_supported"}
                )
        records_payload["sources"] = sorted(
            [record for record in records if record["id"] not in removed],
            key=lambda item: _numeric(item["id"]),
        )
        records = records_payload["sources"]
        meta = records_payload.setdefault("meta", {})
        meta.update(
            {
                "records_count": len(records),
                "verified_primary_count": sum(
                    item["validation"]["status"] == "verified_primary" for item in records
                ),
                "unverified_count": sum(
                    item["validation"]["status"] == "unverified" for item in records
                ),
                "aliases_count": len(aliases),
                "updated_at": date.today().isoformat(),
            }
        )
        aliases_payload.setdefault("meta", {}).update(
            {
                "schema_version": "1.2.0",
                "aliases_count": len(aliases),
                "updated_at": date.today().isoformat(),
            }
        )
        _rebuild_cluster_indexes(clusters_payload, records)

        if "legacy_checks" not in validation_log:
            validation_log["legacy_checks"] = validation_log.pop("checks", [])
        log_meta = validation_log.setdefault("meta", {})
        unresolved = [
            item for item in records if item["validation"]["status"] in {"unverified", "pending"}
        ]
        unresolved_relevance5 = [item for item in unresolved if item.get("релевантность") == 5]
        meta["validation_status"] = (
            "all source validation complete; author and supervisor review pending"
            if not unresolved
            else "source validation in progress"
        )
        log_meta.update(
            {
                "version": "2.0.0",
                "checked_at": date.today().isoformat(),
                "scope": "structured source searches and review decisions",
                "status": (
                    "relevance_5_in_progress"
                    if unresolved_relevance5
                    else (
                        "lower_relevance_validation_in_progress"
                        if unresolved
                        else "all_source_validation_complete_author_review_pending"
                    )
                ),
            }
        )
        log_meta.setdefault("applied_batches", []).append(batch_id)
        validation_log.setdefault("reviews", []).append(
            {
                "batch_id": batch_id,
                "applied_at": date.today().isoformat(),
                "source_ids": payload["source_ids"],
                "decisions": [
                    {
                        "source_id": item["source_id"],
                        "decision": item["decision"],
                        "canonical_id": item.get("canonical_id"),
                        "searches": item["searches"],
                        "claims": item.get("claims", []),
                        "notes": item.get("notes"),
                    }
                    for item in payload["decisions"]
                ],
            }
        )

        matrix_rows = matrix_payload.setdefault("rows", [])
        matrix_rows[:] = [row for row in matrix_rows if row.get("batch_id") != batch_id]
        for decision in payload["decisions"]:
            for claim in decision.get("claims", []):
                matrix_rows.append(
                    {
                        "batch_id": batch_id,
                        "claim": claim.get("claim"),
                        "target_variable": claim.get("target_variable", "unknown"),
                        "population_or_data": claim.get("population_or_data", "unknown"),
                        "source_ids": [decision["source_id"]],
                        "verified_evidence": claim.get("evidence"),
                        "limitations": claim.get("limitation"),
                        "permitted_conclusion": claim.get("permitted_conclusion"),
                    }
                )
        matrix_payload["meta"]["generated_at"] = date.today().isoformat()
        matrix_payload["meta"]["gate"] = "G0_REVISE"
        matrix_payload["meta"]["author_review_required"] = True
        matrix_payload["meta"]["supervisor_decision_required"] = True

        status_counts = Counter(item["validation"]["status"] for item in records)
        relevance5 = [item for item in records if item.get("релевантность") == 5]
        by_relevance = {
            str(level): {
                "canonical_count": len(level_records),
                "status_counts": dict(
                    sorted(Counter(item["validation"]["status"] for item in level_records).items())
                ),
            }
            for level in sorted({item.get("релевантность") for item in records})
            if (level_records := [item for item in records if item.get("релевантность") == level])
        }
        audit_payload["meta"].update(
            {
                "version": "1.2.0",
                "generated_at": date.today().isoformat(),
                "scope": "source validation across relevance levels",
                "gate": "G0_REVISE",
            }
        )
        audit_payload["current_curation"] = {
            "canonical_records": len(records),
            "aliases": len(aliases),
            "validation_status_counts": dict(sorted(status_counts.items())),
            "unresolved_count": len(unresolved),
            "by_relevance": by_relevance,
            "relevance_5": {
                "canonical_count": len(relevance5),
                "status_counts": dict(
                    sorted(Counter(item["validation"]["status"] for item in relevance5).items())
                ),
            },
            "applied_batches": log_meta["applied_batches"],
            "author_review_required": True,
            "supervisor_decision_required": True,
        }
        resource_curation = audit_payload.get("resource_curation", {})
        if resource_curation.get("status_counts"):
            audit_payload["ST"] = {
                "resource_status_counts": resource_curation["status_counts"],
                "resource_count": 104,
            }
        audit_payload["remaining_blockers"] = [
            *(["Source validation still contains unresolved records."] if unresolved else []),
            "Thematic cluster membership still requires domain-expert review.",
            (
                "No open human dataset linking SCS/ECAP to a prespecified clinical "
                "pain outcome was confirmed."
            ),
            (
                "No evidence currently validates transfer from a Drosophila simulator "
                "to human pain or SCS outcomes."
            ),
            (
                "G0 remains G0_REVISE pending author review of the evidence matrix "
                "and a separate supervisor decision."
            ),
        ]

        for name, value in (
            ("records.json", records_payload),
            ("aliases.json", aliases_payload),
            ("clusters.json", clusters_payload),
            ("validation-log.json", validation_log),
            ("audit-report.json", audit_payload),
            ("evidence-matrix.json", matrix_payload),
        ):
            atomic_write_json(root / name, value)
        final = validate_repository(root)
        if not final["ok"]:
            raise DataError("post-review integrity failed: " + "; ".join(final["errors"]))
    except Exception:
        for name, content in originals.items():
            (root / name).write_bytes(content)
        raise
    result.update(
        {
            "applied": True,
            "snapshot": str(snapshot),
            "removed_to_aliases": sorted(removed, key=_numeric),
            "integrity": final,
        }
    )
    return result


def cluster_check(root: Path | str, manifest: Path | str) -> dict[str, Any]:
    root = Path(root).resolve()
    path = Path(manifest).resolve()
    payload = load_json(path)
    cluster = payload.get("cluster", {})
    cluster_id = cluster.get("id")
    source_ids = cluster.get("source_ids", [])
    representative_id = cluster.get("representative_id")
    records = load_json(root / "records.json").get("sources", [])
    clusters = load_json(root / "clusters.json")
    canonical_ids = {record["id"] for record in records}
    occupied_ids = {
        item.get("id")
        for item in [*clusters.get("clusters", []), *clusters.get("retired_clusters", [])]
    }
    errors: list[str] = []
    if not isinstance(cluster_id, str) or not cluster_id.startswith("C"):
        errors.append("cluster.id must be a C-prefixed string")
    elif cluster_id in occupied_ids:
        errors.append(f"cluster id already exists: {cluster_id}")
    if not isinstance(source_ids, list) or not source_ids:
        errors.append("cluster.source_ids must be a non-empty array")
    elif len(source_ids) != len(set(source_ids)):
        errors.append("cluster.source_ids contains duplicates")
    missing = sorted(set(source_ids) - canonical_ids)
    if missing:
        errors.append("unknown canonical source ids: " + ", ".join(missing))
    if representative_id not in source_ids:
        errors.append("cluster.representative_id must be one of cluster.source_ids")
    if not cluster.get("topic") or not cluster.get("synthesis"):
        errors.append("cluster.topic and cluster.synthesis are required")
    return {
        "ok": not errors,
        "path": str(path),
        "cluster_id": cluster_id,
        "source_ids": source_ids,
        "errors": errors,
    }


def cluster_apply(root: Path | str, manifest: Path | str, *, apply: bool = False) -> dict[str, Any]:
    root = Path(root).resolve()
    check = cluster_check(root, manifest)
    result = dict(check)
    result["applied"] = False
    if not check["ok"] or not apply:
        return result
    current = validate_repository(root)
    if not current["ok"]:
        raise DataError("current repository is invalid; repair before assigning a cluster")
    payload = load_json(Path(manifest).resolve())
    requested = payload["cluster"]
    records = load_json(root / "records.json").get("sources", [])
    clusters = load_json(root / "clusters.json")
    by_id = {record["id"]: record for record in records}
    snapshot = snapshot_repository(root, label=f"pre-{payload['meta']['batch_id']}")
    clusters.setdefault("clusters", []).append(
        {
            "id": requested["id"],
            "тема": requested["topic"],
            "синтез": requested["synthesis"],
            "записей": len(requested["source_ids"]),
            "представитель": deepcopy(by_id[requested["representative_id"]]),
            "состав_кластера": requested["source_ids"],
            "validation": {
                "status": "structurally_valid",
                "checked_at": payload["meta"].get("reviewed_at", date.today().isoformat()),
                "content_validation": payload["meta"].get("content_validation", "pending"),
            },
        }
    )
    _rebuild_cluster_indexes(clusters, records)
    atomic_write_json(root / "clusters.json", clusters)
    final = validate_repository(root)
    if not final["ok"]:
        raise DataError(
            f"post-cluster integrity failed; restore from {snapshot}: {'; '.join(final['errors'])}"
        )
    result.update({"applied": True, "snapshot": str(snapshot), "integrity": final})
    return result
