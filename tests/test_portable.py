"""Portable index snapshots: exact round trip, tamper and path safety, no secrets."""

import json
import sqlite3
import zipfile

import pytest

from service.core import DataError
from service.knowledge.portable import export_snapshot, read_manifest, restore_snapshot


@pytest.fixture
def state(tmp_path):
    root = tmp_path / "state"
    (root / "corpus" / "objects").mkdir(parents=True)
    (root / "corpus" / "objects" / "ab12").write_bytes(b"original book bytes")
    (root / "corpus" / "documents.jsonl").write_text('{"id": 1}\n', encoding="utf-8")
    (root / "runtime.env").write_text("RESEARCH_EMBEDDING_KEY=secret\n", encoding="utf-8")
    cache = sqlite3.connect(root / "embeddings.sqlite3")
    cache.execute("CREATE TABLE embeddings (key TEXT PRIMARY KEY, data TEXT)")
    cache.execute("INSERT INTO embeddings VALUES ('k', '[1.0]')")
    cache.commit()
    cache.close()
    return root


MEMBERS = ["corpus/documents.jsonl", "corpus/objects/ab12", "embeddings.sqlite3"]


def test_round_trip_restores_exact_files_and_cache(state, tmp_path):
    archive = tmp_path / "snap.zip"
    record = export_snapshot(state, MEMBERS, archive, index="library", identity={"generation": "g-x"})
    assert record["file_count"] == 3 and record["generation"] == "g-x"
    with zipfile.ZipFile(archive) as bundle:
        assert "runtime.env" not in bundle.namelist()
    target = tmp_path / "fresh"
    result = restore_snapshot(archive, target, index="library")
    assert result["restored_files"] == 3 and result["expected_generation"] == "g-x"
    assert (target / "corpus/objects/ab12").read_bytes() == b"original book bytes"
    cache = sqlite3.connect(target / "embeddings.sqlite3")
    assert cache.execute("SELECT data FROM embeddings").fetchone() == ("[1.0]",)
    cache.close()
    assert not (target / "active.json").exists()  # nothing is served before publish
    with pytest.raises(DataError, match="--force"):
        restore_snapshot(archive, target, index="library")
    assert restore_snapshot(archive, target, index="library", force=True)["overwritten"] == 3
    with pytest.raises(DataError, match="library index, not knowledge"):
        restore_snapshot(archive, tmp_path / "other", index="knowledge")


def test_secrets_and_backend_state_are_never_exported(state, tmp_path):
    for forbidden in ("runtime.env", "active.json", "generations/g-x/indexed.json", "../x"):
        with pytest.raises(DataError, match="unsafe or forbidden"):
            export_snapshot(state, [forbidden], tmp_path / "x.zip", index="library", identity={})


def test_tampered_member_is_rejected_before_anything_is_placed(state, tmp_path):
    archive = tmp_path / "snap.zip"
    export_snapshot(state, MEMBERS, archive, index="library", identity={})
    manifest = read_manifest(archive)
    forged = tmp_path / "forged.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(forged, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            target.writestr(name, b"tampered" if name == "corpus/objects/ab12" else data)
    assert json.loads(zipfile.ZipFile(forged).read("snapshot.json")) == manifest
    fresh = tmp_path / "fresh"
    with pytest.raises(DataError, match="digest mismatch"):
        restore_snapshot(forged, fresh, index="library")
    assert not (fresh / "corpus").exists()
