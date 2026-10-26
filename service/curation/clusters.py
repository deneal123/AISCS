"""Cluster manifests and cluster index maintenance."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

from ..common.errors import DataError
from ..common.jsonio import atomic_write_json, load_json
from ..registry.ids import source_number
from ..registry.layout import data_path
from ..registry.validation import validate_repository
from .snapshots import snapshot_repository


def rebuild_cluster_indexes(clusters: dict[str, Any], records: list[dict[str, Any]]) -> None:
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
            representative_id = sorted(members, key=source_number)[0]
        cluster["представитель"] = deepcopy(by_id[representative_id])
        refs.extend(members)
        active.append(cluster)
    clusters["clusters"] = active
    referenced = set(refs)
    clusters["unclustered_record_ids"] = sorted(canonical_ids - referenced, key=source_number)
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


def cluster_check(root: Path | str, manifest: Path | str) -> dict[str, Any]:
    root = Path(root).resolve()
    path = Path(manifest).resolve()
    payload = load_json(path)
    cluster = payload.get("cluster", {})
    cluster_id = cluster.get("id")
    source_ids = cluster.get("source_ids", [])
    representative_id = cluster.get("representative_id")
    records = load_json(data_path(root, "records.json")).get("sources", [])
    clusters = load_json(data_path(root, "clusters.json"))
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
    records = load_json(data_path(root, "records.json")).get("sources", [])
    clusters = load_json(data_path(root, "clusters.json"))
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
    rebuild_cluster_indexes(clusters, records)
    atomic_write_json(data_path(root, "clusters.json"), clusters)
    final = validate_repository(root)
    if not final["ok"]:
        raise DataError(
            f"post-cluster integrity failed; restore from {snapshot}: {'; '.join(final['errors'])}"
        )
    result.update({"applied": True, "snapshot": str(snapshot), "integrity": final})
    return result
