"""Batch validation workflow for ST resources and implementation candidates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .core import DataError, load_json
from .integrity import validate_repository
from .pipeline import atomic_write_json, snapshot_repository

CURATION_RELATIVE = Path("curation") / "st-resources"
UNRESOLVED = {"url_present_content_not_checked", "needs_exact_url", "unverified"}
DECISIONS = {
    "verified_primary",
    "verified_metadata",
    "partially_verified",
    "rejected",
    "not_applicable",
}
PRIORITY = {"C1": 0, "C3": 1, "C5": 2, "C8": 3}


def iter_resources(payload: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    for category in payload.get("categories", []):
        for subcategory in category.get("подкатегории", []):
            for resource in subcategory.get("ресурсы", []):
                yield category["id"], subcategory["id"], resource


def _resource_name(resource: dict[str, Any]) -> str:
    return str(resource.get("название") or resource.get("компонент") or resource["resource_id"])


def _needs_review(resource: dict[str, Any]) -> bool:
    status = resource.get("статус_валидации")
    return status in UNRESOLVED or (
        status == "partially_verified" and not resource.get("проверенные_утверждения")
    )


def _batch_path(root: Path, batch: Path | str) -> Path:
    candidate = Path(batch)
    if candidate.is_file():
        return candidate.resolve()
    name = candidate.name
    if not name.endswith(".json"):
        name += ".json"
    path = root / CURATION_RELATIVE / "batches" / name
    if not path.is_file():
        raise DataError(f"ST review batch not found: {batch}")
    return path


def build_st_queue(root: Path | str, *, batch_size: int = 15) -> dict[str, Any]:
    root = Path(root).resolve()
    if batch_size < 1:
        raise DataError("batch-size must be positive")
    payload = load_json(root / "ST.json")
    resources = [
        (category, subcategory, resource)
        for category, subcategory, resource in iter_resources(payload)
        if _needs_review(resource)
    ]
    resources.sort(
        key=lambda item: (
            PRIORITY.get(item[0], 9),
            item[0],
            item[1],
            int(item[2]["resource_id"][2:]),
        )
    )
    groups: list[list[tuple[str, str, dict[str, Any]]]] = []
    c1 = [item for item in resources if item[0] == "C1"]
    if c1:
        groups.append(c1)
    remainder = [item for item in resources if item[0] != "C1"]
    for offset in range(0, len(remainder), batch_size):
        groups.append(remainder[offset : offset + batch_size])

    curation = root / CURATION_RELATIVE
    batches_dir = curation / "batches"
    batches_dir.mkdir(parents=True, exist_ok=True)
    log = load_json(root / "validation-log.json")
    applied = log.get("meta", {}).get("applied_resource_batches", [])
    manifests: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=len(applied) + 1):
        batch_id = f"st-batch-{index:03d}"
        path = batches_dir / f"{batch_id}.json"
        manifest = {
            "meta": {
                "batch_id": batch_id,
                "schema_version": "1.0.0",
                "created_at": date.today().isoformat(),
                "status": "awaiting_review",
            },
            "resource_ids": [item[2]["resource_id"] for item in group],
            "resources": [
                {
                    "resource_id": resource["resource_id"],
                    "category_id": category,
                    "subcategory_id": subcategory,
                    "name": _resource_name(resource),
                    "status": resource["статус_валидации"],
                    "url": resource.get("ссылка"),
                }
                for category, subcategory, resource in group
            ],
            "decisions": [],
        }
        if not path.exists() or load_json(path)["meta"]["status"] == "awaiting_review":
            atomic_write_json(path, manifest)
        manifests.append(
            {
                "batch_id": batch_id,
                "resource_ids": manifest["resource_ids"],
                "path": str(path),
            }
        )
    queue = {
        "meta": {
            "version": "1.0.0",
            "generated_at": date.today().isoformat(),
            "status": "in_progress" if resources else "complete",
            "source_statuses": [*sorted(UNRESOLVED), "legacy_partial_without_claims"],
            "resource_count": len(resources),
            "batch_count": len(manifests),
            "batch_size_target": batch_size,
        },
        "batches": manifests,
    }
    atomic_write_json(curation / "queue.json", queue)
    return queue


def st_review_check(root: Path | str, batch: Path | str) -> dict[str, Any]:
    root = Path(root).resolve()
    path = _batch_path(root, batch)
    manifest = load_json(path)
    resources = {
        resource["resource_id"]: resource
        for _, _, resource in iter_resources(load_json(root / "ST.json"))
    }
    manifest_ids = manifest.get("resource_ids", [])
    decisions = manifest.get("decisions", [])
    decision_ids = [item.get("resource_id") for item in decisions if isinstance(item, dict)]
    errors: list[str] = []
    warnings: list[str] = []
    if set(decision_ids) != set(manifest_ids) or len(decision_ids) != len(manifest_ids):
        errors.append("decisions must cover every manifest resource exactly once")
    for decision in decisions:
        resource_id = decision.get("resource_id")
        outcome = decision.get("decision")
        if resource_id not in resources:
            errors.append(f"{resource_id}: resource does not exist")
            continue
        if outcome not in DECISIONS:
            errors.append(f"{resource_id}: unsupported decision {outcome!r}")
        searches = decision.get("searches")
        if not isinstance(searches, list) or not searches:
            errors.append(f"{resource_id}: at least one documented search is required")
        else:
            for search in searches:
                if (
                    not search.get("query")
                    or not search.get("url")
                    or not search.get("accessed_at")
                ):
                    errors.append(f"{resource_id}: every search needs query, URL and date")
        exact_url = decision.get("exact_url")
        if outcome in {"verified_primary", "verified_metadata", "partially_verified"}:
            parsed = urlsplit(str(exact_url or ""))
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append(f"{resource_id}: verified decision requires exact_url")
        if outcome in {"partially_verified", "rejected"} and not decision.get("limitations"):
            errors.append(f"{resource_id}: limitations are required for {outcome}")
        if outcome == "verified_metadata":
            warnings.append(f"{resource_id}: resource content remains metadata-only")
    return {
        "ok": not errors,
        "batch_id": manifest.get("meta", {}).get("batch_id"),
        "path": str(path),
        "resource_count": len(manifest_ids),
        "decision_count": len(decisions),
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
    }


def _status_counts(payload: dict[str, Any]) -> Counter[str]:
    return Counter(resource["статус_валидации"] for _, _, resource in iter_resources(payload))


def st_review_apply(root: Path | str, batch: Path | str, *, apply: bool = False) -> dict[str, Any]:
    root = Path(root).resolve()
    check = st_review_check(root, batch)
    result = dict(check)
    result["applied"] = False
    if not check["ok"] or not apply:
        return result
    path = Path(check["path"])
    manifest = load_json(path)
    batch_id = manifest["meta"]["batch_id"]
    log = load_json(root / "validation-log.json")
    applied = log.setdefault("meta", {}).setdefault("applied_resource_batches", [])
    if batch_id in applied:
        result.update({"ok": True, "already_applied": True})
        return result
    current = validate_repository(root)
    if not current["ok"]:
        raise DataError("current repository is invalid; repair before ST review")
    snapshot = snapshot_repository(root, label=f"pre-{batch_id}")
    mutable_names = ("ST.json", "validation-log.json", "audit-report.json")
    originals = {name: (root / name).read_bytes() for name in mutable_names}
    st = load_json(root / "ST.json")
    audit = load_json(root / "audit-report.json")
    by_id = {resource["resource_id"]: resource for _, _, resource in iter_resources(st)}
    for decision in manifest["decisions"]:
        resource = by_id[decision["resource_id"]]
        resource["статус_валидации"] = decision["decision"]
        resource["проверено"] = decision.get("checked_at", date.today().isoformat())
        if decision.get("exact_url"):
            resource["ссылка"] = decision["exact_url"]
        if decision.get("corrected_purpose"):
            resource["назначение"] = decision["corrected_purpose"]
        resource["проверенные_утверждения"] = decision.get("verified_claims", [])
        resource["ограничения_валидации"] = decision.get("limitations", [])
        resource["примечание_валидации"] = decision.get("note")
    counts = _status_counts(st)
    unresolved = sum(_needs_review(resource) for _, _, resource in iter_resources(st))
    st["meta"].update(
        {
            "дата_валидации": date.today().isoformat(),
            "статусы_ресурсов": dict(sorted(counts.items())),
            "проверено_по_первичному_источнику": counts["verified_primary"],
            "требуют_точной_ссылки": counts["needs_exact_url"],
            "не_подтверждено": counts["unverified"],
            "незавершенных_ресурсов": unresolved,
            "статус_валидации": (
                "пакетная проверка завершена; частичные и отклонённые решения "
                "сохранены с ограничениями"
                if not unresolved
                else "пакетная проверка ресурсов продолжается"
            ),
        }
    )
    applied.append(batch_id)
    log["meta"]["checked_at"] = date.today().isoformat()
    log.setdefault("resource_reviews", []).append(
        {
            "batch_id": batch_id,
            "applied_at": date.today().isoformat(),
            "resource_ids": manifest["resource_ids"],
            "decisions": manifest["decisions"],
        }
    )
    audit["resource_curation"] = {
        "status_counts": dict(sorted(counts.items())),
        "unresolved_count": unresolved,
        "applied_batches": applied,
        "gate": "G0_REVISE",
    }
    audit["ST"] = {
        "resource_status_counts": dict(sorted(counts.items())),
        "resource_count": sum(counts.values()),
    }
    try:
        atomic_write_json(root / "ST.json", st)
        atomic_write_json(root / "validation-log.json", log)
        atomic_write_json(root / "audit-report.json", audit)
        final = validate_repository(root)
        if not final["ok"]:
            raise DataError("post-ST-review integrity failed: " + "; ".join(final["errors"]))
    except Exception:
        for name, content in originals.items():
            (root / name).write_bytes(content)
        raise
    manifest["meta"].update({"status": "applied", "applied_at": date.today().isoformat()})
    atomic_write_json(path, manifest)
    result.update({"applied": True, "snapshot": str(snapshot), "integrity": final})
    return result
