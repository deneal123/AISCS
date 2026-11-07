import hashlib
import json
import sqlite3

import numpy as np
import pytest

from service.infrastructure.connectome.dataset import digest
from service.infrastructure.stimulation.geometry_cache import cache as cache_module
from service.infrastructure.stimulation.geometry_cache.cache import build_cache, iter_cache
from tests.test_packed_geometry_chunk import sources  # noqa: F401
from tests.test_packed_geometry_index import index  # noqa: F401


@pytest.fixture
def fixture(tmp_path, request):
    entries, audited = request.getfixturevalue('sources')
    database, audit, graph = request.getfixturevalue('index')
    with sqlite3.connect(database) as db:
        db.executemany('UPDATE bounds SET sha256 = ? WHERE body_id = ?',
                       [(sha, body) for body, sha in audited.items()])
    report = json.loads(audit.read_text())
    report['index_sha256'] = digest(database)
    audit.write_text(json.dumps(report))
    return {'entries': entries, 'database': database, 'audit': audit, 'graph': graph,
            'directory': tmp_path / 'cache', 'source': tmp_path}


def build(case, **changes):
    args = {'graph_ids': [10, 20], 'graph_sha256': case['graph'],
            'source_index': case['database'], 'source_audit': case['audit'],
            'morphology_directories': [case['source']], 'chunk_neurons': 1}
    return build_cache(case['directory'], **{**args, **changes})


def read(case, manifest, **changes):
    args = {'expected_manifest_sha256': manifest, 'graph_ids': [10, 20],
            'graph_sha256': case['graph'], 'source_index': case['database'],
            'source_audit': case['audit']}
    return list(iter_cache(case['directory'], **{**args, **changes}))


def test_complete_cache_round_trip_and_progress(fixture):
    progress = []
    manifest = build(fixture, progress=lambda done, total: progress.append((done, total)))
    chunks = read(fixture, manifest)
    assert progress == [(1, 2), (2, 2)] and [len(items) for items in chunks] == [1, 1]
    for original, loaded in zip(fixture['entries'], (items[0] for items in chunks), strict=True):
        assert original['skeleton'] == loaded['skeleton']
        for before, after in zip(original['geometry'], loaded['geometry'], strict=True):
            np.testing.assert_array_equal(before, after)


def test_untrusted_manifest_and_corrupted_chunk_are_rejected(fixture):
    manifest = build(fixture)
    path = fixture['directory'] / 'manifest.json'
    raw = path.read_bytes()
    path.write_bytes(raw + b' ')
    with pytest.raises(ValueError, match='manifest checksum'):
        read(fixture, manifest)
    path.write_bytes(raw)
    chunk = fixture['directory'] / 'chunk-000000.bin'
    original = bytearray(chunk.read_bytes())
    original[0] ^= 1
    chunk.write_bytes(original)
    with pytest.raises(ValueError, match='geometry checksum'):
        read(fixture, manifest)


def test_manifest_cannot_redirect_chunk_or_omit_graph_ids(fixture):
    build(fixture)
    path = fixture['directory'] / 'manifest.json'
    metadata = json.loads(path.read_text())
    metadata['chunks'][0]['name'] = '../other.bin'
    raw = json.dumps(metadata).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match='chunk list'):
        read(fixture, hashlib.sha256(raw).hexdigest())
    metadata['chunks'][0]['name'] = 'chunk-000000.bin'
    metadata['chunks'][1]['neurons'][0]['body_id'] = '10'
    raw = json.dumps(metadata).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match='incomplete or out of order'):
        read(fixture, hashlib.sha256(raw).hexdigest())


def test_existing_directory_is_never_overwritten(fixture):
    fixture['directory'].mkdir()
    sentinel = fixture['directory'] / 'keep.txt'
    sentinel.write_text('keep')
    with pytest.raises(FileExistsError):
        build(fixture)
    assert sentinel.read_text() == 'keep'


def test_changed_producer_during_build_is_rejected_and_cleaned(fixture, monkeypatch):
    hashes = iter(['a' * 64, 'b' * 64])
    monkeypatch.setattr(cache_module, '_producer_sha256', lambda: next(hashes))
    with pytest.raises(ValueError, match='producer changed'):
        build(fixture)
    assert not fixture['directory'].exists()


def test_source_change_fails_and_cleans_only_new_cache(fixture):
    # Keep a valid receipt for changed bytes: the independent index must still reject them.
    source = fixture['source'] / 'raw/20.swc'
    source.write_bytes(source.read_bytes() + b'5 0 170 5 3 1 4\n')
    receipt = fixture['source'] / 'receipts/20.json'
    metadata = json.loads(receipt.read_text())
    metadata['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match='source identity'):
        build(fixture)
    assert not fixture['directory'].exists()
