import hashlib
import json
import sqlite3
import sys
import threading

import numpy as np
import pytest

from service.infrastructure.stimulation.geometry_cache.selected import iter_selected_cache
from tests.test_packed_geometry_cache import build
from tests.test_packed_geometry_cache import fixture as geometry_case  # noqa: F401
from tests.test_packed_geometry_chunk import sources  # noqa: F401
from tests.test_packed_geometry_index import index  # noqa: F401


def read(case, manifest, selected, workers=1):
    return list(iter_selected_cache(case['directory'], expected_manifest_sha256=manifest,
                graph_ids=[10, 20], graph_sha256=case['graph'], source_index=case['database'],
                source_audit=case['audit'], selected_ids=selected, workers=workers))


def test_selected_sources_preserve_graph_order_and_exact_geometry(geometry_case):  # noqa: F811
    manifest = build(geometry_case)
    selected = read(geometry_case, manifest, [20, 10])
    assert [int(item['skeleton']['body_id']) for item in selected] == [10, 20]
    for original, restored in zip(geometry_case['entries'], selected, strict=True):
        assert original['skeleton'] == restored['skeleton']
        for before, after in zip(original['geometry'], restored['geometry'], strict=True):
            np.testing.assert_array_equal(before, after)
    assert read(geometry_case, manifest, []) == []
    parallel = read(geometry_case, manifest, [20, 10], workers=2)
    assert [int(item['skeleton']['body_id']) for item in parallel] == [10, 20]
    for expected, actual in zip(selected, parallel, strict=True):
        assert expected['skeleton'] == actual['skeleton']
        for array_a, array_b in zip(expected['geometry'], actual['geometry'], strict=True):
            np.testing.assert_array_equal(array_a, array_b)


def test_reviewed_producer_does_not_bypass_chunk_integrity(geometry_case, monkeypatch):  # noqa: F811
    from service.infrastructure.stimulation.geometry_cache import cache, producer_compatibility

    old, current = 'a' * 64, 'b' * 64
    monkeypatch.setattr(cache, '_producer_sha256', lambda: old)
    manifest = build(geometry_case)
    monkeypatch.setattr(cache, '_producer_sha256', lambda: current)
    monkeypatch.setattr(producer_compatibility, 'REVIEWED_PRODUCERS', {(manifest, old, current)})
    assert len(read(geometry_case, manifest, [10])) == 1
    assert len(list(cache.iter_cache(
        geometry_case['directory'], expected_manifest_sha256=manifest,
        graph_ids=[10, 20], graph_sha256=geometry_case['graph'],
        source_index=geometry_case['database'], source_audit=geometry_case['audit'],
    ))) == 2
    chunk = geometry_case['directory'] / 'chunk-000000.bin'
    damaged = bytearray(chunk.read_bytes())
    damaged[0] ^= 1
    chunk.write_bytes(damaged)
    with pytest.raises(ValueError):
        read(geometry_case, manifest, [10])
    with pytest.raises(ValueError):
        list(cache.iter_cache(
            geometry_case['directory'], expected_manifest_sha256=manifest,
            graph_ids=[10, 20], graph_sha256=geometry_case['graph'],
            source_index=geometry_case['database'], source_audit=geometry_case['audit'],
        ))


def test_changed_reader_source_falls_back_without_skipping_validation(geometry_case, monkeypatch):  # noqa: F811
    from service.infrastructure.stimulation.geometry_cache import chunk, selected_chunk

    manifest = build(geometry_case)
    called = []
    original = chunk.read_chunk

    def observed(*args, **kwargs):
        called.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(selected_chunk, 'REVIEWED_CHUNK_SHA256', '0' * 64)
    monkeypatch.setattr(chunk, 'read_chunk', observed)
    assert int(read(geometry_case, manifest, [20])[0]['skeleton']['body_id']) == 20
    assert called


@pytest.mark.parametrize('selected', [[10, 10], [99], [True], ['10'], [0]])
def test_rejects_invalid_selected_ids(geometry_case, selected):  # noqa: F811
    manifest = build(geometry_case)
    with pytest.raises(ValueError, match='selected geometry IDs'):
        read(geometry_case, manifest, selected)


def test_verifies_selected_chunks_and_does_not_read_unselected(geometry_case):  # noqa: F811
    manifest = build(geometry_case)
    first = geometry_case['directory'] / 'chunk-000000.bin'
    data = bytearray(first.read_bytes())
    data[0] ^= 1
    first.write_bytes(data)
    assert int(read(geometry_case, manifest, [20])[0]['skeleton']['body_id']) == 20
    with pytest.raises(ValueError, match='checksum'):
        read(geometry_case, manifest, [10])


def test_parallel_corruption_fails_closed_and_joins_workers(geometry_case):  # noqa: F811
    manifest = build(geometry_case)
    first = geometry_case['directory'] / 'chunk-000000.bin'
    data = bytearray(first.read_bytes())
    data[0] ^= 1
    first.write_bytes(data)

    with pytest.raises(ValueError, match='checksum'):
        read(geometry_case, manifest, [10, 20], workers=2)
    assert all(not thread.name.startswith('geometry-chunk') for thread in threading.enumerate())


def test_rejects_manifest_tampering_and_omitted_graph_ids(geometry_case):  # noqa: F811
    manifest = build(geometry_case)
    path = geometry_case['directory'] / 'manifest.json'
    raw = path.read_bytes()
    path.write_bytes(raw + b' ')
    with pytest.raises(ValueError, match='manifest checksum'):
        read(geometry_case, manifest, [20])
    metadata = json.loads(raw)
    metadata['chunks'][0]['neurons'][0]['body_id'] = '20'
    altered = json.dumps(metadata).encode()
    path.write_bytes(altered)
    with pytest.raises(ValueError, match='incomplete or out of order'):
        read(geometry_case, hashlib.sha256(altered).hexdigest(), [20])


def test_screening_with_selected_cache_matches_swc_and_fails_closed(
    geometry_case, tmp_path, monkeypatch,  # noqa: F811
):
    from scripts.audit_morphology_radii import audit as audit_radii
    from scripts.build_morphology_radii import build as build_radii
    from service.infrastructure.connectome.dataset import digest
    from service.infrastructure.stimulation.contacts import screen as contact_screen
    from service.infrastructure.stimulation.contacts.screen import screen_contact_positions

    # Enclose both source trees; this test concerns the screening/reader contract.
    with sqlite3.connect(geometry_case['database']) as db:
        db.execute('UPDATE bounds SET min_x=0, max_x=2, min_y=-1, max_y=1, min_z=-1, max_z=1')
    proof = json.loads(geometry_case['audit'].read_text())
    proof['index_sha256'] = digest(geometry_case['database'])
    geometry_case['audit'].write_text(json.dumps(proof))
    manifest = build(geometry_case)
    radius_db, radius_audit = tmp_path / 'radii.db', tmp_path / 'radii.audit.json'
    build_radii(geometry_case['database'], geometry_case['audit'], radius_db,
                [geometry_case['source']])
    radius_audit.write_text(json.dumps(audit_radii(geometry_case['database'],
        geometry_case['audit'], radius_db, [geometry_case['source']])))
    args = (geometry_case['database'], geometry_case['audit'], radius_db, radius_audit,
            [10, 20], geometry_case['graph'], [geometry_case['source']],
            [[.9, .02, .02], [1.2, .02, .02], [30., 0., 0.]], .1)
    options = {'directory': geometry_case['directory'], 'expected_manifest_sha256': manifest,
               'source_index': geometry_case['database'], 'source_audit': geometry_case['audit']}
    direct = screen_contact_positions(*args)
    calls = []
    original = contact_screen.packed_contact_clearances

    def observed(*args, **kwargs):
        calls.append(kwargs['_conservative_prefilter'])
        return original(*args, **kwargs)

    monkeypatch.setattr(contact_screen, 'packed_contact_clearances', observed)
    accelerated = screen_contact_positions(*args, geometry_cache=options)
    assert accelerated == direct
    assert calls and all(value == (sys.platform == 'linux') for value in calls)
    assert accelerated['potential_intersections']
    path = geometry_case['directory'] / 'chunk-000000.bin'
    raw = bytearray(path.read_bytes())
    raw[0] ^= 1
    path.write_bytes(raw)
    with pytest.raises(ValueError, match='checksum'):
        screen_contact_positions(*args, geometry_cache=options, workers=2)
    assert all(not thread.name.startswith(('geometry-read', 'geometry-chunk'))
               for thread in threading.enumerate())
