"""Finalize metadata after all relevance-5 review batches have been applied."""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

from service.core import DataError, load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CURATION = DATA / "curation" / "relevance-5"


def main() -> None:
    initial = validate_repository(DATA)
    if not initial["ok"]:
        raise DataError("repository is invalid before finalization")
    records = load_json(DATA / "records.json")
    aliases = load_json(DATA / "aliases.json")
    resources = load_json(DATA / "ST.json")
    log = load_json(DATA / "validation-log.json")
    audit = load_json(DATA / "audit-report.json")
    matrix = load_json(DATA / "evidence-matrix.json")
    queue = load_json(CURATION / "queue.json")

    sources = records["sources"]
    relevance5 = [item for item in sources if item.get("релевантность") == 5]
    unresolved = [
        item["id"]
        for item in relevance5
        if item["validation"]["status"] in {"unverified", "pending"}
    ]
    if unresolved:
        raise DataError(f"relevance-5 still has unresolved records: {unresolved}")

    batch_paths = sorted((CURATION / "batches").glob("batch-*.json"))
    batches = [load_json(path) for path in batch_paths]
    applied = log.get("meta", {}).get("applied_batches", [])
    batch_ids = [batch["meta"]["batch_id"] for batch in batches]
    if set(batch_ids) != set(applied):
        raise DataError("curation batch files and applied_batches do not match")
    processed = sum(len(batch["source_ids"]) for batch in batches)
    snapshot = snapshot_repository(DATA, label="pre-relevance5-finalization")

    today = date.today().isoformat()
    records["meta"].update(
        {
            "validation_status": (
                "relevance-5 validation complete; lower-relevance records pending"
            ),
            "updated_at": today,
        }
    )
    log["meta"].update(
        {
            "checked_at": today,
            "status": "relevance_5_complete_author_review_pending",
        }
    )
    queue["meta"].update(
        {
            "status": "complete",
            "completed_at": today,
            "source_count": processed,
            "batch_count": len(applied),
            "initial_unverified_count": processed,
            "remaining_queue_generated_after_batch_001": 121,
            "processed_batch_source_count": processed,
            "remaining_unverified_count": 0,
            "applied_batch_count": len(applied),
        }
    )
    queue["batches"] = [
        {
            "batch_id": batch["meta"]["batch_id"],
            "source_ids": batch["source_ids"],
            "path": str(path.resolve()),
        }
        for path, batch in zip(batch_paths, batches, strict=True)
    ]
    matrix["meta"].update(
        {
            "generated_at": today,
            "gate": "G0_REVISE",
            "author_review_required": True,
            "supervisor_decision_required": True,
        }
    )
    status_counts = Counter(item["validation"]["status"] for item in sources)
    relevance_counts = Counter(item["validation"]["status"] for item in relevance5)
    audit["meta"].update(
        {
            "generated_at": today,
            "scope": "completed relevance-5 source validation",
            "gate": "G0_REVISE",
        }
    )
    audit["current_curation"] = {
        "canonical_records": len(sources),
        "aliases": len(aliases["aliases"]),
        "validation_status_counts": dict(sorted(status_counts.items())),
        "relevance_5": {
            "canonical_count": len(relevance5),
            "status_counts": dict(sorted(relevance_counts.items())),
            "unresolved_count": 0,
            "processed_batch_source_count": processed,
        },
        "applied_batches": applied,
        "author_review_required": True,
        "supervisor_decision_required": True,
    }

    matched_resources = [
        resource
        for category in resources.get("categories", [])
        for subcategory in category.get("подкатегории", [])
        for resource in subcategory.get("ресурсы", [])
        if resource.get("название") == "US20220323766A1"
    ]
    if len(matched_resources) != 1:
        raise DataError("expected exactly one directly linked US20220323766A1 resource")
    matched_resources[0].update(
        {
            "ссылка": "https://patents.google.com/patent/US20220323766A1/en",
            "статус_валидации": "partially_verified",
            "проверено": today,
            "примечание_валидации": (
                "Идентификатор и страница патента подтверждены; патент не является "
                "эмпирическим доказательством (records S289; alias S392)."
            ),
        }
    )

    for path, batch in zip(batch_paths, batches, strict=True):
        batch["meta"].update({"status": "applied", "applied_at": today})
        atomic_write_json(path, batch)
    atomic_write_json(DATA / "records.json", records)
    atomic_write_json(DATA / "validation-log.json", log)
    atomic_write_json(DATA / "audit-report.json", audit)
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "ST.json", resources)
    atomic_write_json(CURATION / "queue.json", queue)

    report = validate_repository(DATA)
    if not report["ok"]:
        raise DataError("final integrity failed: " + "; ".join(report["errors"]))
    print(
        {
            "snapshot": str(snapshot),
            "processed": processed,
            "canonical_relevance5": len(relevance5),
            "statuses": dict(sorted(relevance_counts.items())),
            "gate": "G0_REVISE",
        }
    )


if __name__ == "__main__":
    main()
