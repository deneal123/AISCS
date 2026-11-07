import json
import sqlite3

import pytest

from service.infrastructure.connectome.dataset import digest
from service.infrastructure.stimulation.geometry_cache import index as packed_geometry_index


@pytest.fixture
def index(tmp_path):
    path, audit = tmp_path / 'bounds.sqlite', tmp_path / 'audit.json'
    graph = 'a' * 64
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute('CREATE TABLE bounds (body_id INTEGER PRIMARY KEY, status TEXT, sha256 TEXT, '
                   'min_x REAL, max_x REAL, min_y REAL, max_y REAL, min_z REAL, max_z REAL)')
        db.executemany('INSERT INTO metadata VALUES (?, ?)', [
            ('format', 'malecns-verified-bounds-v1'), ('graph_sha256', graph),
            ('neurons', '2'), ('algorithm_sha256', 'b' * 64),
        ])
        db.executemany('INSERT INTO bounds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [
            (10, 'ok', 'c' * 64, 0, 1, 0, 1, 0, 1),
            (20, 'ok', 'd' * 64, -1, 0, -1, 0, -1, 0),
        ])
    audit.write_text(json.dumps({'format': 'malecns-bounds-audit-v1', 'graph_sha256': graph,
                                 'index_sha256': digest(path), 'verified': 2}))
    return path, audit, graph


def test_returns_audited_source_identities(index):
    path, audit, graph = index
    sources, index_hash = packed_geometry_index.audited_geometry_sources(path, audit, [10, 20],
                                                                         graph)
    assert sources == {10: 'c' * 64, 20: 'd' * 64}
    assert index_hash == digest(path)


@pytest.mark.parametrize('ids', [[], [10, 10], [20, 10], [True, 20], [0, 20], [10, 2**63]])
def test_rejects_invalid_graph_ids_before_using_index(index, ids):
    path, audit, graph = index
    with pytest.raises(ValueError, match='graph IDs'):
        packed_geometry_index.audited_geometry_sources(path, audit, ids, graph)


def test_rejects_changed_index_and_wrong_audit(index):
    path, audit, graph = index
    with sqlite3.connect(path) as db:
        db.execute('UPDATE bounds SET sha256 = ? WHERE body_id = 10', ('e' * 64,))
    with pytest.raises(ValueError, match='changed since audit'):
        packed_geometry_index.audited_geometry_sources(path, audit, [10, 20], graph)
    with pytest.raises(ValueError, match='audit does not match'):
        packed_geometry_index.audited_geometry_sources(path, audit, [10, 20], 'f' * 64)


@pytest.mark.parametrize('mutation', [
    "UPDATE bounds SET status = 'missing' WHERE body_id = 10",
    'DELETE FROM bounds WHERE body_id = 10',
    'UPDATE bounds SET min_x = 2, max_x = 1 WHERE body_id = 10',
    "UPDATE metadata SET value = 'different' WHERE key = 'format'",
])
def test_rejects_semantically_invalid_index_even_if_digest_matches(index, mutation):
    path, audit, graph = index
    with sqlite3.connect(path) as db:
        db.execute(mutation)
    report = json.loads(audit.read_text())
    report['index_sha256'] = digest(path)
    audit.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        packed_geometry_index.audited_geometry_sources(path, audit, [10, 20], graph)


def test_rejects_index_changed_during_read(index, monkeypatch):
    path, audit, graph = index
    hashes = iter([digest(path), '0' * 64])
    monkeypatch.setattr(packed_geometry_index, 'digest', lambda _: next(hashes))
    with pytest.raises(ValueError, match='changed while reading'):
        packed_geometry_index.audited_geometry_sources(path, audit, [10, 20], graph)
