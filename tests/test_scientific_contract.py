from copy import deepcopy
from pathlib import Path

from service.core import load_json
from service.integrity import _validate_scientific_artifacts, validate_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _resources() -> set[str]:
    payload = load_json(DATA / "ST.json")
    return {
        resource["resource_id"]
        for category in payload["categories"]
        for subcategory in category.get("подкатегории", [])
        for resource in subcategory.get("ресурсы", [])
    }


def _sources() -> set[str]:
    return {source["id"] for source in load_json(DATA / "records.json")["sources"]}


def test_scientific_contract_and_human_matrix_pass_repository_gate() -> None:
    result = validate_repository(DATA)
    assert result["ok"] is True, result["errors"]
    contract = load_json(DATA / "scientific-contract.json")
    matrix = load_json(DATA / "human-dataset-matrix.json")
    assert len(contract["entities"]) == 6
    assert len(contract["experiments"]) == 4
    assert {item["id"] for item in contract["stop_criteria"]} == {
        "STOP-H1",
        "STOP-H2-A",
        "STOP-H2-B",
        "STOP-H3-A",
        "STOP-H3-B",
    }
    assert all(isinstance(item["target_construct"], str) for item in matrix["datasets"])


def test_scientific_artifact_gate_rejects_bad_reference_and_mixed_target() -> None:
    contract = load_json(DATA / "scientific-contract.json")
    matrix = load_json(DATA / "human-dataset-matrix.json")
    vocab = load_json(DATA / "vocabularies.json")

    bad_contract = deepcopy(contract)
    bad_contract["entities"][0]["source_refs"].append("S999999")
    errors = _validate_scientific_artifacts(
        bad_contract, matrix, _sources(), _resources(), vocab
    )
    assert any("S999999" in error for error in errors)

    bad_matrix = deepcopy(matrix)
    bad_matrix["compatibility_rules"][0]["target_construct"] = "self_reported_pain"
    errors = _validate_scientific_artifacts(
        contract, bad_matrix, _sources(), _resources(), vocab
    )
    assert any("mixed targets" in error for error in errors)


def test_todo_progress_is_exactly_63_of_165() -> None:
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    assert todo.count("- [x]") + todo.count(". [x]") == 63
    assert todo.count("- [ ]") + todo.count(". [ ]") == 102
