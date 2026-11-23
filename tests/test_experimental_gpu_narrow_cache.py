import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.narrow_cache import (
    NarrowCacheError,
    NarrowCellCache,
    bodies_digest,
    cache_key,
    decode_cell,
    encode_cell,
    inventory,
)
from service.infrastructure.stimulation.experimental_gpu.population_replay import (
    iter_cached_batches,
)

GEOMETRY = 'a' * 64
INDEX = 'b' * 64


def _params():
    from types import SimpleNamespace

    return SimpleNamespace(source_um=(0., 0., 0.), return_um=(1., 1., 1.), current_na=-300.,
                           conductivity_s_m=.3, clearance_um=1., axial_resistivity=100.,
                           capacitance=1., nseg=1)


def _metadata(chunks=2, per_chunk=3):
    return {'chunks': [{'neurons': [{'body_id': str(chunk * per_chunk + offset)}
                                     for offset in range(per_chunk)]}
                        for chunk in range(chunks)]}


def _cell(body, segments):
    """One cell in exactly the shape a recorded population pass narrows it to."""
    starts = np.arange(segments * 3, dtype=float).reshape(segments, 3)
    return {
        'id': body,
        'geometry': {
            'parents': np.arange(segments, dtype=np.int64) - 1,
            'conductances': np.full(segments + 1, .25),
            'segment_nodes': np.arange(segments, dtype=np.int64),
            'area': np.full(segments, 1.5),
            'starts_um': starts,
            'ends_um': starts + 1.,
            'midpoints_um': starts + .5,
            'endpoint_radii_um': np.full((segments, 2), .4),
            'edge_node_ids': np.full(segments, body, dtype=np.int64),
            'segment_index': np.arange(segments, dtype=np.int32),
            'grid': None,
        },
        'field_current_na': np.full(segments, -.75),
        'events': [],
        'initial_voltage_mv': -65.,
        'initial_gates': np.array([.05, .3, .55]),
        'morphology_sha256': GEOMETRY,
    }


def _key():
    return cache_key(geometry_sha256=GEOMETRY, source_index_sha256=INDEX,
                     params=_params(), recording=True, events=True, reroot=False)


def _built(tmp_path, cells_by_group, *, chunks=2):
    cache = NarrowCellCache(tmp_path)
    writer = cache.writer(_key(), {'geometry_sha256': GEOMETRY, 'recording': True})
    for group, cells in enumerate(cells_by_group):
        for cell in cells:
            writer.add(group, cell)
    meta = writer.commit()
    return cache, meta


def test_a_cell_survives_the_flat_form_byte_for_byte():
    layout = [('geometry', 'parents', '<i8', 1), ('geometry', 'endpoint_radii_um', '<f8', 2),
              ('cell', 'field_current_na', '<f8', 1), ('cell', 'initial_gates', '<f8', 1)]
    original = _cell(7, 5)
    rebuilt = decode_cell(encode_cell(original, layout), layout)
    assert rebuilt['id'] is None
    assert rebuilt['initial_voltage_mv'] == -65.
    assert rebuilt['initial_gates'].dtype == np.float64
    assert np.array_equal(rebuilt['initial_gates'], original['initial_gates'])
    assert rebuilt['geometry']['parents'].dtype == np.int64
    assert np.array_equal(rebuilt['geometry']['parents'], original['geometry']['parents'])
    assert np.array_equal(rebuilt['geometry']['endpoint_radii_um'],
                          original['geometry']['endpoint_radii_um'])
    assert np.array_equal(rebuilt['field_current_na'], original['field_current_na'])
    assert rebuilt['morphology_sha256'] == GEOMETRY
    # The two fields the layout cannot carry come back in their inert form.
    assert rebuilt['events'] == [] and rebuilt['geometry']['grid'] is None


def test_cache_replays_cells_in_build_order_and_verifies_them(tmp_path):
    groups = [[_cell(0, 3), _cell(1, 4)], [_cell(2, 2)]]
    cache, meta = _built(tmp_path, groups)
    assert meta['cells'] == 3 and meta['chunks'] == 2
    store = cache.open(_key(), chunks=2, bodies=bodies_digest([0, 1, 2]))
    assert store is not None
    try:
        assert store.groups == 2 and store.cells == 3
        assert [cell['id'] for cell in store.group(0)] == [0, 1]
        assert [cell['id'] for cell in store.group(1)] == [2]
        assert np.array_equal(store.group(0)[1]['geometry']['area'], np.full(4, 1.5))
    finally:
        store.close()


def test_an_entry_from_another_chunk_inventory_is_a_miss(tmp_path):
    cache, _meta = _built(tmp_path, [[_cell(0, 2)], [_cell(1, 2)]])
    # Same key, same cell count, different chunks: the replay would reproduce
    # other pool boundaries, so it must recompute rather than reuse.
    assert cache.open(_key(), chunks=3, bodies=bodies_digest([0, 1])) is None
    assert cache.open(_key(), chunks=2, bodies=bodies_digest([0, 2])) is None
    assert cache.open(_key(), chunks=2, bodies=bodies_digest([0, 1])) is not None


def test_a_corrupted_record_is_an_error_not_a_measurement(tmp_path):
    cache, meta = _built(tmp_path, [[_cell(0, 8)], [_cell(1, 8)]])
    payload = cache.entry(_key()) / 'payload.bin'
    raw = bytearray(payload.read_bytes())
    raw[20] ^= 0xFF
    payload.write_bytes(bytes(raw))
    # The index still describes the payload length, so the entry opens; the
    # damage is caught on the record that carries it.
    store = cache.open(_key(), chunks=2, bodies=bodies_digest([0, 1]))
    assert store is not None
    try:
        with pytest.raises(NarrowCacheError):
            store.group(0)
    finally:
        store.close()


def test_a_truncated_payload_is_a_miss(tmp_path):
    cache, meta = _built(tmp_path, [[_cell(0, 4)], [_cell(1, 4)]])
    payload = cache.entry(_key()) / 'payload.bin'
    payload.write_bytes(payload.read_bytes()[:-5])
    assert cache.open(_key(), chunks=2, bodies=bodies_digest([0, 1])) is None


def test_an_entry_without_metadata_is_a_miss(tmp_path):
    cache, _meta = _built(tmp_path, [[_cell(0, 4)], [_cell(1, 4)]])
    (cache.entry(_key()) / 'meta.json').unlink()
    assert cache.open(_key(), chunks=2, bodies=bodies_digest([0, 1])) is None


def test_a_cell_carrying_events_or_a_grid_is_refused(tmp_path):
    cache = NarrowCellCache(tmp_path)
    writer = cache.writer(_key(), {'geometry_sha256': GEOMETRY, 'recording': True})
    eventful = _cell(0, 3)
    eventful['events'] = [{'child_node_id': 1, 'position': .5, 'time_ms': 2., 'weight_us': 3.}]
    with pytest.raises(NarrowCacheError):
        writer.add(0, eventful)
    gridded = _cell(1, 3)
    gridded['geometry']['grid'] = [(1, 0, 3)]
    with pytest.raises(NarrowCacheError):
        writer.add(0, gridded)


def test_an_empty_entry_is_refused(tmp_path):
    cache = NarrowCellCache(tmp_path)
    writer = cache.writer(_key(), {'geometry_sha256': GEOMETRY})
    with pytest.raises(NarrowCacheError):
        writer.commit()


def test_cached_batches_cover_every_cell_once_and_respect_the_pool(tmp_path):
    groups = [[_cell(chunk * 3 + offset, 10) for offset in range(3)] for chunk in range(2)]
    cache, _meta = _built(tmp_path, groups)
    store = cache.open(_key(), chunks=2, bodies=bodies_digest(range(6)))
    assert store is not None
    try:
        batches = list(iter_cached_batches(store, segment_budget=1000, max_cells=4,
                                           pool_cells=3, pool_segments=10_000))
    finally:
        store.close()
    flat = [cell['id'] for batch in batches for cell in batch]
    assert flat == list(range(6))
    assert all(len(batch) <= 4 for batch in batches)
    assert [len(batch) for batch in batches] == [3, 3]


def test_the_cache_key_covers_every_input_that_changes_a_narrowed_cell():
    from types import SimpleNamespace

    base = cache_key(geometry_sha256=GEOMETRY, source_index_sha256=INDEX,
                     params=_params(), recording=True, events=True, reroot=False)
    assert base == cache_key(geometry_sha256=GEOMETRY, source_index_sha256=INDEX,
                             params=_params(), recording=True, events=True, reroot=False)
    for changed in ({'recording': False}, {'events': False}, {'reroot': True}):
        assert base != cache_key(geometry_sha256=GEOMETRY, source_index_sha256=INDEX,
                                 params=_params(), recording=changed.get('recording', True),
                                 events=changed.get('events', True),
                                 reroot=changed.get('reroot', False))
    wider = SimpleNamespace(**{**vars(_params()), 'conductivity_s_m': .5})
    assert base != cache_key(geometry_sha256=GEOMETRY, source_index_sha256=INDEX,
                             params=wider, recording=True, events=True, reroot=False)
    with pytest.raises(ValueError):
        cache_key(geometry_sha256='short', source_index_sha256=INDEX, params=_params(),
                  recording=True, events=True, reroot=False)


def test_inventory_covers_the_chunks_a_limit_visits():
    metadata = _metadata(chunks=3, per_chunk=2)
    assert inventory(metadata, None) == (3, bodies_digest(range(6)))
    assert inventory(metadata, [2, 0]) == (2, bodies_digest([4, 5, 0, 1]))

def test_a_second_walk_after_the_reader_finishes_is_read_inline(tmp_path):
    """The reader walks one order; a later group must not wait for a thread that ended."""
    groups = [[_cell(0, 2)], [_cell(1, 3)], [_cell(2, 4)]]
    cache, _meta = _built(tmp_path, groups, chunks=3)
    store = cache.open(_key(), chunks=3, bodies=bodies_digest([0, 1, 2]))
    assert store is not None
    try:
        store.start_read_ahead([0, 1], depth=1)
        assert [cell['id'] for cell in store.group(0)] == [0]
        assert [cell['id'] for cell in store.group(1)] == [1]
        # The reader has now returned; asking for the group it never queued must
        # read it here rather than block forever on a condition nothing notifies.
        assert [cell['id'] for cell in store.group(2)] == [2]
    finally:
        store.close()
