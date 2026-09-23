from pathlib import Path

from service.integrity import validate_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def test_current_repository_passes_integrity_gate() -> None:
    report = validate_repository(DATA)
    assert report["ok"], report["errors"]
    assert report["counts"] | {"archive_manifests": 0} == {
        "sources": 148,
        "aliases": 268,
        "active_clusters": 43,
        "retired_clusters": 11,
        "resources": 104,
        "archive_manifests": 0,
    }
    assert report["counts"]["archive_manifests"] >= 11


def test_schema_1_2_validated_the_pre_deduplication_350_record_snapshot() -> None:
    snapshot = DATA / "archive" / "2026-09-22T102852Z-pre-batch-001"
    report = validate_repository(snapshot)
    assert report["ok"], report["errors"]
    assert report["counts"]["sources"] == 350
