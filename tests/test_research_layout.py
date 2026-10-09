from pathlib import Path

import pytest

from service.core import DocumentSidecar, atomic_write_json

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("organized", [True, False])
def test_research_import_accepts_current_and_historical_layout(
    tmp_path: Path, organized: bool
) -> None:
    data = tmp_path / "research" / "data"
    data.mkdir(parents=True)
    atomic_write_json(data / "records.json", {"sources": [{"id": "S999"}]})
    atomic_write_json(data / "ST.json", {"categories": []})
    contract = data / "research" if organized else data
    evidence = data / "evidence" if organized else data
    contract.mkdir(exist_ok=True)
    evidence.mkdir(exist_ok=True)
    atomic_write_json(contract / "scientific-contract.json", {"fixture": "contract"})
    atomic_write_json(evidence / "human-dataset-matrix.json", {"fixture": "dataset"})
    result = DocumentSidecar(ROOT).import_research(data, ["S999"], apply=False)
    assert result["ok"]
    assert result["applied"] is False
    assert result["selected_refs"] == ["S999"]
