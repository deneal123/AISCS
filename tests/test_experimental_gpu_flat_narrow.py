"""Tests for the selective flat narrow-cell cache."""
import hashlib
import json
from pathlib import Path

import numpy as np

from service.infrastructure.stimulation.experimental_gpu.flat_narrow import (
    CELL_KEYS, FORMAT, GEOMETRY_KEYS, FlatNarrowCache, chunk_name)


def _cell(body, segments=4):
    return {
        'id': body,
        'field_current_na': np.linspace(-1.0, 1.0, segments),
        'initial_voltage_mv': -65.0,
        'initial_gates': np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6]),
        'morphology_sha256': 'a' * 64,
        'events': [],
        'geometry': {
            'parents': np.arange(segments, dtype=np.int32),
            'conductances': np.full(segments, 0.5),
            'segment_nodes': np.arange(segments, dtype=np.int32),
            'area': np.full(segments, 2.0),
            'grid': None,
            'starts_um': np.zeros((segments, 3)),
            'ends_um': np.ones((segments, 3)),
            'midpoints_um': np.full((segments, 3), 0.5),
            'endpoint_radii_um': np.full((segments, 2), 0.3),
            'edge_node_ids': np.arange(segments, dtype=np.int64),
            'segment_index': np.arange(segments, dtype=np.int32),
        },
    }


def _metadata(graph='g' * 64, index='i' * 64):
    return {'graph_sha256': graph, 'source_index_sha256': index}


def test_roundtrip_restores_every_array(tmp_path):
    store = FlatNarrowCache(tmp_path / 'c', threshold=0)
    store.begin_build()
    cells = {body: _cell(body) for body in (7, 11)}
    for body, cell in cells.items():
        store.add(body, cell)
    store.flush(0)
    store.commit(_metadata(), 'm' * 64)
    reader = FlatNarrowCache(tmp_path / 'c', threshold=0)
    assert reader.compatible(_metadata(), 'm' * 64) is not None
    loaded = reader.load(0)
    assert set(loaded) == {7, 11}
    original = cells[11]
    restored = loaded[11]
    assert restored['id'] == 11
    assert restored['initial_voltage_mv'] == -65.0
    assert restored['morphology_sha256'] == 'a' * 64
    np.testing.assert_array_equal(restored['geometry']['midpoints_um'],
                                  original['geometry']['midpoints_um'])
    np.testing.assert_array_equal(restored['field_current_na'],
                                  original['field_current_na'])
    assert restored['geometry']['grid'] is None


def test_instances_own_their_buffers(tmp_path):
    """A restored array must not keep the whole blob alive."""
    store = FlatNarrowCache(tmp_path / 'c', threshold=0)
    store.begin_build()
    store.add(3, _cell(3))
    store.flush(0)
    store.commit(_metadata(), 'm' * 64)
    reader = FlatNarrowCache(tmp_path / 'c', threshold=0)
    reader.compatible(_metadata(), 'm' * 64)
    restored = reader.load(0)[3]
    blob = Path(tmp_path / 'c' / (chunk_name(0) + '.bin')).read_bytes()
    assert len(blob) > 0
    # np.frombuffer keeps the blob alive through .base, which is why the reader
    # never hands out a view of the mmap-ed file: it copies into own buffers.
    for key in GEOMETRY_KEYS:
        value = restored['geometry'][key]
        assert value is None or value.base is not None or value.flags.owndata


def test_corrupted_chunk_is_a_miss(tmp_path):
    store = FlatNarrowCache(tmp_path / 'c', threshold=0)
    store.begin_build()
    store.add(3, _cell(3))
    store.flush(0)
    store.commit(_metadata(), 'm' * 64)
    path = tmp_path / 'c' / (chunk_name(0) + '.bin')
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0xFF
    path.write_bytes(bytes(raw))
    reader = FlatNarrowCache(tmp_path / 'c', threshold=0)
    assert reader.compatible(_metadata(), 'm' * 64) is not None
    assert reader.load(0) is None
    assert reader.receipt()['read']['misses'] == 1


def test_identity_rejects_another_inventory(tmp_path):
    store = FlatNarrowCache(tmp_path / 'c', threshold=0)
    store.begin_build()
    store.add(3, _cell(3))
    store.flush(0)
    store.commit(_metadata(), 'm' * 64)
    for wrong in (_metadata(graph='x' * 64), _metadata(index='x' * 64)):
        reader = FlatNarrowCache(tmp_path / 'c', threshold=0)
        assert reader.compatible(wrong, 'm' * 64) is None
    reader = FlatNarrowCache(tmp_path / 'c', threshold=0)
    assert reader.compatible(_metadata(), 'n' * 64) is None


def test_threshold_selects_only_wide_cells(tmp_path):
    store = FlatNarrowCache(tmp_path / 'c', threshold=8)
    assert store.wants(_cell(1, segments=9)) is True
    assert store.wants(_cell(1, segments=8)) is True
    assert store.wants(_cell(1, segments=7)) is False


def test_empty_chunk_writes_nothing(tmp_path):
    store = FlatNarrowCache(tmp_path / 'c', threshold=100)
    store.begin_build()
    store.flush(0)
    assert not (tmp_path / 'c').exists() or not list((tmp_path / 'c').glob('*.bin'))
    assert store.receipt()['written']['chunks'] == 0


def test_receipt_counts_what_it_did(tmp_path):
    store = FlatNarrowCache(tmp_path / 'c', threshold=0)
    store.begin_build()
    for body in (1, 2, 3):
        store.add(body, _cell(body))
    store.flush(0)
    receipt = store.receipt()
    assert receipt['written']['chunks'] == 1
    assert receipt['written']['cells'] == 3
    assert receipt['written']['bytes'] > 0