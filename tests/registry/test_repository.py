from pathlib import Path

from service.common.jsonio import load_json
from service.registry.layout import data_path
from service.registry.repository import ResearchRepository

ROOT = Path(__file__).resolve().parents[2]
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
    assert {item["id"] for item in result["items"]} == {"S088", "S730"}
    assert ResearchRepository(DATA).get_source("S039")["validation"]["status"] == "partially_verified"


def test_jsonl_export_has_one_line_per_source() -> None:
    repository = ResearchRepository(DATA)
    assert len(repository.export_jsonl().splitlines()) == len(load_json(data_path(DATA, "records.json"))["sources"])
