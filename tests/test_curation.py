import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from service.core import load_json, sha256
from service.curation import build_queue, cluster_apply, review_apply
from service.integrity import validate_source_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


@pytest.mark.parametrize(
    ("status", "exclusion_reason"),
    [
        ("verified_primary", None),
        ("verified_metadata", None),
        ("partially_verified", None),
        ("rejected", "unverifiable"),
    ],
)
def test_schema_1_2_accepts_review_outcomes(status: str, exclusion_reason: str | None) -> None:
    record = deepcopy(load_json(DATA / "staging" / "source-record.template.json"))
    record["id"] = "S999999"
    record["название"] = f"Schema fixture: {status}"
    record["validation"].update(
        {
            "status": status,
            "screening_status": (
                "excluded_unverifiable" if status == "rejected" else "included_core"
            ),
            "exclusion_reason": exclusion_reason,
        }
    )
    record["relations"] = [
        {
            "type": "preprint_of",
            "target_id": None,
            "external_id": "doi:10.0000/journal-version",
            "note": "Preprint and journal entities remain distinct.",
        }
    ]
    errors = validate_source_record(
        record,
        load_json(DATA / "source-record.schema.json"),
        load_json(DATA / "vocabularies.json"),
    )
    assert not errors


def test_batches_cover_all_review_decision_types() -> None:
    decisions = {
        decision["decision"]
        for path in (DATA / "curation" / "relevance-5" / "batches").glob("*.json")
        for decision in load_json(path)["decisions"]
    }
    assert decisions == {
        "alias",
        "partially_verified",
        "rejected",
        "verified_metadata",
        "verified_primary",
    }


def test_applied_batch_is_idempotent() -> None:
    tracked = [
        DATA / name
        for name in (
            "records.json",
            "aliases.json",
            "clusters.json",
            "validation-log.json",
            "audit-report.json",
            "evidence-matrix.json",
        )
    ]
    before = {path.name: sha256(path) for path in tracked}
    result = review_apply(DATA, "batch-001", apply=True)
    after = {path.name: sha256(path) for path in tracked}
    assert result["ok"] is True
    assert result["already_applied"] is True
    assert result["applied"] is False
    assert after == before


def test_batch_008_changed_no_source_outside_manifest() -> None:
    before = load_json(DATA / "archive" / "2026-09-22T104041Z-pre-batch-008" / "records.json")[
        "sources"
    ]
    after = load_json(
        DATA / "archive" / "2026-09-22T105635Z-pre-relevance5-finalization" / "records.json"
    )["sources"]
    manifest = load_json(DATA / "curation" / "relevance-5" / "batches" / "batch-008.json")[
        "source_ids"
    ]
    before_by_id = {item["id"]: item for item in before}
    after_by_id = {item["id"]: item for item in after}
    changed = {
        source_id
        for source_id in before_by_id.keys() | after_by_id.keys()
        if before_by_id.get(source_id) != after_by_id.get(source_id)
    }
    assert changed <= set(manifest)


def test_all_relevance_5_records_have_terminal_decisions() -> None:
    records = load_json(DATA / "records.json")["sources"]
    relevance5 = [item for item in records if item["релевантность"] == 5]
    assert len(relevance5) == 53
    assert not {
        item["id"]
        for item in relevance5
        if item["validation"]["status"] in {"unverified", "pending"}
    }
    for item in relevance5:
        if item["validation"]["status"] != "rejected":
            assert any(item["identifiers"].values())


def test_completed_queue_matches_all_applied_batches() -> None:
    queue = load_json(DATA / "curation" / "relevance-5" / "queue.json")
    log = load_json(DATA / "validation-log.json")
    batch_ids = [item["batch_id"] for item in queue["batches"]]
    source_ids = [source_id for item in queue["batches"] for source_id in item["source_ids"]]
    assert queue["meta"]["status"] == "complete"
    assert queue["meta"]["source_count"] == len(source_ids) == 142
    assert queue["meta"]["batch_count"] == len(batch_ids) == 8
    relevance5_applied = [
        batch_id for batch_id in log["meta"]["applied_batches"] if batch_id.startswith("batch-")
    ]
    assert batch_ids == relevance5_applied


def test_lower_relevance_queues_use_distinct_directories_and_ids(tmp_path: Path) -> None:
    data = tmp_path / "data"
    shutil.copytree(DATA, data)
    records_path = data / "records.json"
    records = load_json(records_path)
    selected = {}
    for relevance in (3, 4):
        record = next(item for item in records["sources"] if item["релевантность"] == relevance)
        record["validation"].update(
            {
                "status": "unverified",
                "screening_status": "pending",
                "full_text_status": "not_checked",
            }
        )
        selected[relevance] = record["id"]
    atomic_write_json(records_path, records)

    queue3 = build_queue(data, relevance=3, status="unverified", batch_size=25)
    queue4 = build_queue(data, relevance=4, status="unverified", batch_size=25)

    assert queue3["meta"]["source_count"] == 1
    assert queue4["meta"]["source_count"] == 1
    assert queue3["batches"][0]["source_ids"] == [selected[3]]
    assert queue4["batches"][0]["source_ids"] == [selected[4]]
    assert all(item["batch_id"].startswith("r3-batch-") for item in queue3["batches"])
    assert all(item["batch_id"].startswith("r4-batch-") for item in queue4["batches"])
    assert (data / "curation" / "relevance-3" / "queue.json").is_file()
    assert (data / "curation" / "relevance-4" / "queue.json").is_file()
    assert load_json(data / "curation" / "relevance-5" / "queue.json")["meta"]["relevance"] == 5


def test_all_source_records_have_terminal_decisions_and_identifiers() -> None:
    records = load_json(DATA / "records.json")["sources"]
    assert not {
        item["id"] for item in records if item["validation"]["status"] in {"unverified", "pending"}
    }
    for item in records:
        if item["validation"]["status"] != "rejected":
            assert any(item["identifiers"].values()), item["id"]


@pytest.mark.parametrize("relevance", [3, 4, 5])
def test_curation_queues_are_complete(relevance: int) -> None:
    queue = load_json(DATA / "curation" / f"relevance-{relevance}" / "queue.json")
    assert queue["meta"]["status"] == "complete"
    assert queue["meta"]["remaining_unverified_count"] == 0


def test_cluster_assignment_is_dry_run_then_atomic_apply(tmp_path: Path) -> None:
    data = tmp_path / "data"
    shutil.copytree(DATA, data)
    manifest = tmp_path / "cluster.json"
    atomic_write_json(
        manifest,
        {
            "meta": {
                "batch_id": "test-cluster-001",
                "reviewed_at": "2026-09-23",
                "content_validation": "pending",
            },
            "cluster": {
                "id": "C999",
                "topic": "Test cluster",
                "synthesis": "Test-only assignment.",
                "representative_id": "S002",
                "source_ids": ["S002", "S003"],
            },
        },
    )
    before = sha256(data / "clusters.json")
    dry_run = cluster_apply(data, manifest, apply=False)
    assert dry_run["ok"] is True
    assert dry_run["applied"] is False
    assert sha256(data / "clusters.json") == before

    applied = cluster_apply(data, manifest, apply=True)
    assert applied["ok"] is True
    assert applied["applied"] is True
    clusters = load_json(data / "clusters.json")
    added = next(item for item in clusters["clusters"] if item["id"] == "C999")
    assert added["состав_кластера"] == ["S002", "S003"]
