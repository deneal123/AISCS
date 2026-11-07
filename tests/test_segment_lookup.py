import hashlib
import json
import sqlite3

import pytest

from service.infrastructure.stimulation.segment_lookup import segment_ordinals


def test_lookup_returns_verified_digest_without_changing_default_result(tmp_path, monkeypatch):
    index = tmp_path / "segments.sqlite"
    with sqlite3.connect(index) as db:
        db.execute("CREATE TABLE metadata (key TEXT, value TEXT)")
        db.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            [
                ("format", "malecns-segment-rtree-v1"),
                ("source_sha256", "a" * 64),
                ("graph_sha256", "b" * 64),
                ("neurons", "1"),
            ],
        )
        db.execute(
            "CREATE TABLE boxes (id INTEGER, min_x REAL, max_x REAL, "
            "min_y REAL, max_y REAL, min_z REAL, max_z REAL)"
        )
        db.execute("INSERT INTO boxes VALUES (0, 0, 1, 0, 1, 0, 1)")
    digest = hashlib.sha256(index.read_bytes()).hexdigest()
    audit = tmp_path / "audit.json"
    audit.write_text(
        json.dumps(
            {
                "format": "malecns-segment-audit-v1",
                "verified": 1,
                "source_sha256": "a" * 64,
                "graph_sha256": "b" * 64,
                "index_sha256": digest,
            }
        ),
        encoding="utf8",
    )
    kwargs = dict(
        source_sha="a" * 64, graph_sha="b" * 64, count=1, contacts=[[0.5, 0.5, 0.5]], radius_um=0.1
    )
    assert segment_ordinals(index, audit, **kwargs) == {0}
    assert segment_ordinals(index, audit, **kwargs, return_digest=True) == ({0}, digest)
    with pytest.raises(ValueError, match="digest option"):
        segment_ordinals(index, audit, **kwargs, return_digest=1)
    cache = tmp_path / 'cache'
    monkeypatch.setenv('GENERATOR_SEGMENT_SNAPSHOT_DIR', str(cache))
    assert segment_ordinals(index, audit, **kwargs) == {0}
    snapshot = cache / f'segments-{digest}.sqlite'
    assert snapshot.is_file()
    # Local snapshots identify the independently audited bytes. Corruption of
    # the cache must never be silently accepted or used as an empty result.
    with snapshot.open('ab') as output:
        output.write(b'corrupt')
    with pytest.raises(ValueError, match='changed since audit'):
        segment_ordinals(index, audit, **kwargs)


def test_snapshot_rejects_changed_source_without_leaving_partial_files(tmp_path):
    from service.infrastructure.stimulation.segment_lookup import _local_snapshot

    source = tmp_path / 'source'
    source.write_bytes(b'changed')
    directory = tmp_path / 'snapshots'
    with pytest.raises(ValueError, match='changed since audit'):
        _local_snapshot(source, 'a' * 64, directory)
    assert list(directory.iterdir()) == []
