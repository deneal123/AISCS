from pathlib import Path

from service.core import ResearchRepository, load_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def test_alias_resolves_to_canonical_record() -> None:
    source = ResearchRepository(DATA).get_source("S063")
    assert source is not None
    assert source["id"] == "S031"
    assert source["alias_resolution"]["requested_id"] == "S063"


def test_search_and_evidence_filters_compose() -> None:
    result = ResearchRepository(DATA).list_sources(
        query="PainMonit", validation_status="verified_primary"
    )
    assert result["total"] == 2
    assert {item["id"] for item in result["items"]} == {"S039", "S730"}


def test_jsonl_export_has_one_line_per_source() -> None:
    repository = ResearchRepository(DATA)
    assert len(repository.export_jsonl().splitlines()) == len(load_json(DATA / "records.json")["sources"])
