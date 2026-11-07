import sqlite3

import pytest

from scripts.build_morphology_bounds import build_index


def test_snapshot_is_resumable_and_keeps_missing_and_invalid_status(tmp_path, monkeypatch):
    def read(body_id, _directories):
        if body_id == 2:
            raise FileNotFoundError()
        if body_id == 3:
            raise ValueError("bad receipt")
        return {"sha256": "a" * 64, "bounds_um": [[1, 2], [3, 4], [5, 6]]}

    monkeypatch.setattr("scripts.build_morphology_bounds.read_skeleton", read)
    target = tmp_path / "bounds.sqlite"
    assert build_index([1, 2, 3], [], target, "graph", limit=1)["statuses"] == {"ok": 1}
    result = build_index([1, 2, 3], [], target, "graph")
    assert result["processed_now"] == 2
    assert result["statuses"] == {"ok": 1, "source_missing": 1, "invalid_source": 1}
    assert build_index([1, 2, 3], [], target, "graph")["processed_now"] == 0
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT min_x, max_z FROM bounds WHERE body_id=1").fetchone() == (1, 6)
    with pytest.raises(ValueError, match="another graph"):
        build_index([1, 2, 3], [], target, "other")


def test_rejects_unsorted_or_duplicate_ids(tmp_path):
    with pytest.raises(ValueError, match="Invalid index inputs"):
        build_index([2, 1], [], tmp_path / "bounds.sqlite", "graph")
    with pytest.raises(ValueError, match="Invalid index inputs"):
        build_index([1, 1], [], tmp_path / "bounds.sqlite", "graph")
