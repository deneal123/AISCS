import json
from copy import deepcopy
from pathlib import Path

from service.core import load_json
from service.pipeline import new_candidate, review_candidates

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def test_new_candidate_uses_next_free_id() -> None:
    candidate = new_candidate(DATA, "A newly discovered source")
    assert candidate["id"] == "S738"
    assert candidate["название"] == "A newly discovered source"
    assert candidate["validation"]["status"] == "unverified"


def test_candidate_stage_accepts_new_well_formed_record(tmp_path: Path) -> None:
    candidate = load_json(DATA / "staging" / "source-record.template.json")
    candidate["id"] = "S999998"
    candidate["название"] = "Synthetic fixture source that cannot collide"
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
    report = review_candidates(DATA, path)
    assert report["ok"], report["errors"]


def test_candidate_stage_rejects_exact_duplicate(tmp_path: Path) -> None:
    first = deepcopy(load_json(DATA / "records.json")["sources"][0])
    first["id"] = "S999997"
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(first, ensure_ascii=False), encoding="utf-8")
    report = review_candidates(DATA, path)
    assert not report["ok"]
    assert any("exact duplicate" in error for error in report["errors"])


def test_candidate_stage_rejects_existing_exact_url(tmp_path: Path) -> None:
    candidate = deepcopy(load_json(DATA / "staging" / "source-record.template.json"))
    candidate["id"] = "S999996"
    candidate["название"] = "Different title pointing to an existing repository"
    candidate["identifiers"]["exact_url"] = "https://github.com/nftechie/doomfly/"
    path = tmp_path / "url-duplicate.json"
    path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
    report = review_candidates(DATA, path)
    assert not report["ok"]
    assert "S999996: exact_url already belongs to S200" in report["errors"]
