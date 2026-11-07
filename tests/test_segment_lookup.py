import hashlib
import json
import sqlite3

import numpy as np
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
    assert segment_ordinals(index, audit, **{**kwargs, 'contacts': [[np.float32(.5)] * 3],
                                              'radius_um': np.float32(.1)}) == {0}
    assert segment_ordinals(index, audit, **kwargs, return_digest=True) == ({0}, digest)
    with pytest.raises(ValueError, match="digest option"):
        segment_ordinals(index, audit, **kwargs, return_digest=1)
    cache = tmp_path / 'cache'
    monkeypatch.setenv('GENERATOR_SEGMENT_SNAPSHOT_DIR', str(cache))
    assert segment_ordinals(index, audit, **kwargs) == {0}
    snapshot = cache / f'segments-{digest}.sqlite'
    assert snapshot.is_file()
    # A corrupt local snapshot is replaced only with independently audited bytes.
    with snapshot.open('ab') as output:
        output.write(b'corrupt')
    assert segment_ordinals(index, audit, **kwargs) == {0}
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == digest
    with snapshot.open('ab') as output:
        output.write(b'corrupt')
    with index.open('ab') as output:
        output.write(b'corrupt source')
    with pytest.raises(ValueError, match='source changed since audit'):
        segment_ordinals(index, audit, **kwargs)
    assert not list(cache.glob('*.tmp'))


def test_snapshot_rejects_changed_source_without_leaving_partial_files(tmp_path):
    from service.infrastructure.stimulation.segment_lookup import _local_snapshot

    source = tmp_path / 'source'
    source.write_bytes(b'changed')
    directory = tmp_path / 'snapshots'
    with pytest.raises(ValueError, match='changed since audit'):
        _local_snapshot(source, 'a' * 64, directory)
    assert list(directory.iterdir()) == []


@pytest.mark.parametrize(('contacts', 'radius', 'count'), [
    ([], 1, 1), ([[0, 0, 0]] * 65, 1, 1), ([[0, 0]], 1, 1),
    ([[float('nan'), 0, 0]], 1, 1), ([[0, float('inf'), 0]], 1, 1),
    ([[True, 0, 0]], 1, 1), ([[0, 0, 0]], float('nan'), 1),
    ([[0, 0, 0]], True, 1), ([[0, 0, 0]], -1, 1), ([[0, 0, 0]], 10**400, 1),
    ([[1e308, 0, 0]], 1e308, 1), ([[0, 0, 0]], 1, True),
])
def test_lookup_rejects_invalid_queries_before_reading_indexes(tmp_path, contacts, radius, count):
    with pytest.raises(ValueError, match='Invalid segment query'):
        segment_ordinals(tmp_path / 'missing', tmp_path / 'missing-audit',
                         source_sha='a' * 64, graph_sha='b' * 64,
                         count=count, contacts=contacts, radius_um=radius)
