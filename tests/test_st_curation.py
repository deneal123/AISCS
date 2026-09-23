from pathlib import Path

from service.core import load_json, sha256
from service.st_curation import iter_resources, st_review_apply

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def resource_map(payload: dict) -> dict[str, dict]:
    return {resource["resource_id"]: resource for _, _, resource in iter_resources(payload)}


def test_st_schema_1_2_has_stable_unique_ids_and_matching_counters() -> None:
    payload = load_json(DATA / "ST.json")
    resources = resource_map(payload)
    assert payload["meta"]["resource_schema_version"] == "1.2.0"
    assert len(resources) == 104
    assert set(resources) == {f"ST{index:03d}" for index in range(1, 105)}
    assert payload["meta"]["незавершенных_ресурсов"] == 0
    assert payload["meta"]["статусы_ресурсов"] == {
        "partially_verified": 19,
        "rejected": 18,
        "verified_primary": 67,
    }


def test_applied_st_batches_are_idempotent() -> None:
    tracked = [DATA / "ST.json", DATA / "validation-log.json", DATA / "audit-report.json"]
    for batch_id in tuple(f"st-batch-{index:03d}" for index in range(1, 8)):
        before = {path.name: sha256(path) for path in tracked}
        result = st_review_apply(DATA, batch_id, apply=True)
        after = {path.name: sha256(path) for path in tracked}
        assert result["ok"] is True
        assert result["already_applied"] is True
        assert result["applied"] is False
        assert after == before


def test_applied_st_batches_changed_no_resource_outside_manifest() -> None:
    transitions = (
        (
            "st-batch-001",
            DATA / "archive" / "2026-09-22T111833Z-pre-st-batch-001" / "ST.json",
            DATA / "archive" / "2026-09-22T113215Z-pre-st-batch-002" / "ST.json",
        ),
        (
            "st-batch-002",
            DATA / "archive" / "2026-09-22T113215Z-pre-st-batch-002" / "ST.json",
            DATA / "archive" / "2026-09-22T113545Z-pre-st-batch-003" / "ST.json",
        ),
        (
            "st-batch-003",
            DATA / "archive" / "2026-09-22T113545Z-pre-st-batch-003" / "ST.json",
            DATA / "archive" / "2026-09-22T114144Z-pre-st-batch-004" / "ST.json",
        ),
        (
            "st-batch-004",
            DATA / "archive" / "2026-09-22T114144Z-pre-st-batch-004" / "ST.json",
            DATA / "archive" / "2026-09-22T114825Z-pre-st-batch-005" / "ST.json",
        ),
        (
            "st-batch-005",
            DATA / "archive" / "2026-09-22T114825Z-pre-st-batch-005" / "ST.json",
            DATA / "archive" / "2026-09-22T115248Z-pre-st-batch-006" / "ST.json",
        ),
        (
            "st-batch-006",
            DATA / "archive" / "2026-09-22T115248Z-pre-st-batch-006" / "ST.json",
            DATA / "archive" / "2026-09-22T115248Z-pre-st-batch-007" / "ST.json",
        ),
        (
            "st-batch-007",
            DATA / "archive" / "2026-09-22T115248Z-pre-st-batch-007" / "ST.json",
            DATA / "ST.json",
        ),
    )
    for batch_id, before_path, after_path in transitions:
        before = resource_map(load_json(before_path))
        after = resource_map(load_json(after_path))
        manifest_ids = set(
            load_json(DATA / "curation" / "st-resources" / "batches" / f"{batch_id}.json")[
                "resource_ids"
            ]
        )
        changed = {
            resource_id for resource_id in before if before[resource_id] != after[resource_id]
        }
        assert changed == manifest_ids


def test_st_queue_is_complete_after_all_batches() -> None:
    queue = load_json(DATA / "curation" / "st-resources" / "queue.json")
    ids = [resource_id for batch in queue["batches"] for resource_id in batch["resource_ids"]]
    assert queue["meta"]["status"] == "complete"
    assert queue["meta"]["resource_count"] == len(ids) == 0
    assert queue["meta"]["batch_count"] == 0
    assert len(ids) == len(set(ids))
    applied_ids = {
        resource_id
        for batch_id in tuple(f"st-batch-{index:03d}" for index in range(1, 8))
        for resource_id in load_json(
            DATA / "curation" / "st-resources" / "batches" / f"{batch_id}.json"
        )["resource_ids"]
    }
    assert not set(ids) & applied_ids
    # Nine resources were already verified before the batch workflow was introduced.
    assert len(applied_ids) == 95
