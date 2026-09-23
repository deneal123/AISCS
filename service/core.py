"""Read-only core for the JSON research knowledge base."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DataError(RuntimeError):
    """The on-disk knowledge base is missing or internally inconsistent."""


def default_data_dir() -> Path:
    configured = os.environ.get("RESEARCH_DATA_DIR")
    return (
        Path(configured).resolve() if configured else Path(__file__).resolve().parents[1] / "data"
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DataError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle, object_pairs_hook=_reject_duplicate_keys)
    except (OSError, json.JSONDecodeError) as exc:
        raise DataError(f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DataError(f"top-level JSON value must be an object: {path}")
    return payload


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


@dataclass(frozen=True)
class Bundle:
    records: dict[str, Any]
    clusters: dict[str, Any]
    resources: dict[str, Any]
    aliases: dict[str, Any]
    vocabularies: dict[str, Any]
    fingerprint: str


class ResearchRepository:
    """Small cached repository over the canonical JSON artifacts.

    Files are reloaded when their size or modification time changes. Every public
    method returns newly constructed containers, so an HTTP caller cannot mutate
    the cached corpus.
    """

    FILES = (
        "records.json",
        "clusters.json",
        "ST.json",
        "aliases.json",
        "vocabularies.json",
        "scientific-contract.json",
        "human-dataset-matrix.json",
    )

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.data_dir = Path(data_dir).resolve() if data_dir else default_data_dir()
        self._lock = threading.RLock()
        self._stamp: tuple[tuple[int, int], ...] | None = None
        self._bundle: Bundle | None = None

    def _file_stamp(self) -> tuple[tuple[int, int], ...]:
        try:
            return tuple(
                (path.stat().st_mtime_ns, path.stat().st_size)
                for path in (self.data_dir / name for name in self.FILES)
            )
        except OSError as exc:
            raise DataError(f"research data is incomplete in {self.data_dir}: {exc}") from exc

    def bundle(self) -> Bundle:
        with self._lock:
            stamp = self._file_stamp()
            if self._bundle is not None and stamp == self._stamp:
                return self._bundle
            payloads = {name: load_json(self.data_dir / name) for name in self.FILES}
            fingerprint_source = "|".join(
                sha256(self.data_dir / name) for name in self.FILES
            ).encode("ascii")
            fingerprint = hashlib.sha256(fingerprint_source).hexdigest().upper()[:16]
            self._bundle = Bundle(
                records=payloads["records.json"],
                clusters=payloads["clusters.json"],
                resources=payloads["ST.json"],
                aliases=payloads["aliases.json"],
                vocabularies=payloads["vocabularies.json"],
                fingerprint=fingerprint,
            )
            self._stamp = stamp
            return self._bundle

    def metadata(self) -> dict[str, Any]:
        bundle = self.bundle()
        return {
            "fingerprint": bundle.fingerprint,
            "records": dict(bundle.records.get("meta", {})),
            "clusters": dict(bundle.clusters.get("meta", {})),
            "resources": dict(bundle.resources.get("meta", {})),
            "aliases": dict(bundle.aliases.get("meta", {})),
        }

    def get_source(self, source_id: str, *, resolve_alias: bool = True) -> dict[str, Any] | None:
        bundle = self.bundle()
        requested_id = source_id.upper()
        canonical_id = requested_id
        alias_entry = bundle.aliases.get("aliases", {}).get(requested_id)
        if alias_entry and resolve_alias:
            canonical_id = alias_entry["canonical_id"]
        for source in bundle.records.get("sources", []):
            if source.get("id") == canonical_id:
                result = dict(source)
                if canonical_id != requested_id:
                    result["alias_resolution"] = {
                        "requested_id": requested_id,
                        "canonical_id": canonical_id,
                        "reason": alias_entry.get("reason"),
                    }
                return result
        return None

    def list_sources(
        self,
        *,
        query: str | None = None,
        validation_status: str | None = None,
        screening_status: str | None = None,
        evidence_role: str | None = None,
        target_construct: str | None = None,
        risk_flag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        sources = self.bundle().records.get("sources", [])
        needle = query.casefold().strip() if query else ""

        def matches(source: dict[str, Any]) -> bool:
            validation = source.get("validation", {})
            evidence = source.get("evidence", {})
            if validation_status and validation.get("status") != validation_status:
                return False
            if screening_status and validation.get("screening_status") != screening_status:
                return False
            if evidence_role and evidence.get("evidence_role") != evidence_role:
                return False
            if target_construct and evidence.get("target_construct") != target_construct:
                return False
            if risk_flag and risk_flag not in source.get("risk_flags", []):
                return False
            if needle:
                searchable = " ".join(
                    str(source.get(field) or "")
                    for field in (
                        "id",
                        "название",
                        "авторы",
                        "издание",
                        "модальность",
                        "задача",
                        "метод",
                        "датасет",
                        "ограничения",
                    )
                ).casefold()
                if needle not in searchable:
                    return False
            return True

        matched = [dict(source) for source in sources if matches(source)]
        return {
            "items": matched[offset : offset + limit],
            "total": len(matched),
            "limit": limit,
            "offset": offset,
        }

    def list_clusters(self, *, include_retired: bool = False) -> list[dict[str, Any]]:
        bundle = self.bundle()
        clusters = [dict(item) for item in bundle.clusters.get("clusters", [])]
        if include_retired:
            clusters.extend(dict(item) for item in bundle.clusters.get("retired_clusters", []))
        return clusters

    def get_cluster(self, cluster_id: str) -> dict[str, Any] | None:
        wanted = cluster_id.upper()
        for cluster in self.list_clusters(include_retired=True):
            if cluster.get("id") == wanted:
                return cluster
        return None

    def get_cluster_context(
        self, cluster_id: str, *, expand_sources: bool = False
    ) -> dict[str, Any] | None:
        cluster = self.get_cluster(cluster_id)
        if cluster is None:
            return None
        result = deepcopy(cluster)
        if expand_sources:
            source_ids = result.get("состав_кластера", [])
            result["sources"] = [
                source for source_id in source_ids if (source := self.get_source(source_id))
            ]
        return result

    def list_resources(
        self,
        *,
        query: str | None = None,
        validation_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        needle = query.casefold().strip() if query else ""
        matched: list[dict[str, Any]] = []
        for category in self.bundle().resources.get("categories", []):
            for subcategory in category.get("подкатегории", []):
                for resource in subcategory.get("ресурсы", []):
                    if (
                        validation_status
                        and resource.get("статус_валидации") != validation_status
                    ):
                        continue
                    item = deepcopy(resource)
                    item["category"] = {
                        "id": category.get("id"),
                        "name": category.get("название"),
                    }
                    item["subcategory"] = {
                        "id": subcategory.get("id"),
                        "name": subcategory.get("название"),
                    }
                    if needle and needle not in json.dumps(
                        item, ensure_ascii=False, sort_keys=True
                    ).casefold():
                        continue
                    matched.append(item)
        return {
            "items": matched[offset : offset + limit],
            "total": len(matched),
            "limit": limit,
            "offset": offset,
        }

    def list_evidence(
        self,
        *,
        query: str | None = None,
        source_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        payload = load_json(self.data_dir / "evidence-matrix.json")
        needle = query.casefold().strip() if query else ""
        wanted_id = source_id.upper() if source_id else None
        rows: list[dict[str, Any]] = []
        for row in payload.get("rows", []):
            if wanted_id and wanted_id not in row.get("source_ids", []):
                continue
            if needle and needle not in json.dumps(
                row, ensure_ascii=False, sort_keys=True
            ).casefold():
                continue
            rows.append(deepcopy(row))
        return {
            "items": rows[offset : offset + limit],
            "total": len(rows),
            "limit": limit,
            "offset": offset,
            "gate": payload.get("meta", {}).get("gate"),
        }

    def get_source_context(self, source_id: str) -> dict[str, Any] | None:
        source = self.get_source(source_id)
        if source is None:
            return None
        canonical_id = source.get("id")
        clusters = [
            cluster
            for cluster in self.list_clusters(include_retired=True)
            if canonical_id in cluster.get("состав_кластера", [])
        ]
        outgoing = deepcopy(source.get("relations", []))
        incoming: list[dict[str, Any]] = []
        for candidate in self.bundle().records.get("sources", []):
            for relation in candidate.get("relations", []):
                if relation.get("target_id") == canonical_id:
                    incoming.append(
                        {
                            "source_id": candidate.get("id"),
                            "type": relation.get("type"),
                            "note": relation.get("note"),
                        }
                    )
        return {
            "source": source,
            "clusters": deepcopy(clusters),
            "relations": {"outgoing": outgoing, "incoming": incoming},
            "evidence": self.list_evidence(source_id=str(canonical_id), limit=100)["items"],
        }

    def evidence_summary(self) -> dict[str, Any]:
        sources = self.bundle().records.get("sources", [])
        return {
            "total": len(sources),
            "validation_status": dict(
                sorted(
                    Counter(
                        s.get("validation", {}).get("status", "missing") for s in sources
                    ).items()
                )
            ),
            "screening_status": dict(
                sorted(
                    Counter(
                        s.get("validation", {}).get("screening_status", "missing") for s in sources
                    ).items()
                )
            ),
            "evidence_role": dict(
                sorted(
                    Counter(
                        s.get("evidence", {}).get("evidence_role", "missing") for s in sources
                    ).items()
                )
            ),
            "target_construct": dict(
                sorted(
                    Counter(
                        s.get("evidence", {}).get("target_construct", "missing") for s in sources
                    ).items()
                )
            ),
            "risk_flags": dict(
                sorted(Counter(flag for s in sources for flag in s.get("risk_flags", [])).items())
            ),
        }

    def export_jsonl(self) -> str:
        return "".join(
            json.dumps(source, ensure_ascii=False, sort_keys=True) + "\n"
            for source in self.bundle().records.get("sources", [])
        )
