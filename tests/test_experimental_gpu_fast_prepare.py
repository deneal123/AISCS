import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.fast_cable import CACHE_RECORD
from service.infrastructure.stimulation.experimental_gpu.fast_prepare import (
    FastPrepareError,
    _usable,
    iter_prepared_chunks,
    read_manifest,
)


def test_rejected_cells_are_not_silently_omitted():
    chunk = SimpleNamespace(error_codes=np.array([0, 3, 0], dtype=np.int32))
    with pytest.raises(FastPrepareError, match='Rejected morphology 20: code 3'):
        _usable(chunk, [10, 20, 30])
    rejected = []
    kept = _usable(chunk, [10, 20, 30], on_invalid=lambda body, code: rejected.append((body, code)))
    assert kept == [0, 2]
    assert rejected == [(20, 3)]


def test_fast_preparation_exposes_interpolated_endpoint_radii():
    from service.infrastructure.stimulation.experimental_gpu.fast_cable import Params, prepare_chunk
    from service.infrastructure.stimulation.experimental_gpu.fast_prepare import cells_from_chunk

    rows = np.array([(0., 0., 0., 2., -1, 1), (10., 0., 0., 1., 0, 2)],
                    dtype=CACHE_RECORD)
    params = Params(source_um=(100., 100., 100.), return_um=(200., 100., 100.),
                    current_na=1., conductivity_s_m=.3, clearance_um=.1, nseg=3)
    chunk = prepare_chunk(rows, np.array([0]), np.array([2]), params,
                          bodies=[10], store_bounds=True)
    geometry = cells_from_chunk(chunk)[0]['geometry']
    np.testing.assert_allclose(geometry['endpoint_radii_um'],
                               [[2., 5 / 3], [5 / 3, 4 / 3], [4 / 3, 1.]])
    np.testing.assert_allclose(geometry['midpoints_um'],
                               (geometry['starts_um'] + geometry['ends_um']) / 2)


def test_rejected_codes_must_match_population():
    with pytest.raises(FastPrepareError, match='error codes'):
        _usable(SimpleNamespace(error_codes=np.array([0])), [10, 20])


@pytest.mark.parametrize('limit', [0, -1, True, 1.5])
def test_invalid_chunk_limit_is_rejected_before_reading(limit):
    with pytest.raises(FastPrepareError, match='chunk limit'):
        list(iter_prepared_chunks({}, audited_sources={}, params=None, limit=limit))


def test_population_batches_forward_rejected_cell_callback(monkeypatch):
    from service.infrastructure.stimulation.experimental_gpu.population_replay import (
        iter_cell_batches,
    )

    rejected = []
    def prepare(_metadata, *, on_invalid, **_kwargs):
        on_invalid(20, 3)
        yield [10], [{'id': 10, 'geometry': {'area': np.ones(1)}}], None

    monkeypatch.setattr('service.infrastructure.stimulation.experimental_gpu.'
                        'population_replay.iter_prepared_chunks', prepare)
    batches = list(iter_cell_batches({'chunks': []}, audited_sources={}, params=None,
        segment_budget=10, on_invalid=lambda body, code: rejected.append((body, code))))
    assert [cell['id'] for batch in batches for cell in batch] == [10]
    assert rejected == [(20, 3)]


def test_snapshot_inventory_rejects_duplicate_or_missing_cells_before_reading(tmp_path):
    def descriptor(position, body):
        return {'name': f'chunk-{position:06d}.bin', 'format': 'malecns-packed-geometry-chunk-v1',
                'vertices': 1, 'bytes': CACHE_RECORD.itemsize, 'sha256': 'a' * 64,
                'neurons': [{'body_id': str(body), 'source_sha256': 'b' * 64,
                             'offset': 0, 'count': 1}]}

    sources = {10: 'b' * 64, 20: 'b' * 64}
    metadata = {'directory': tmp_path, 'neurons': 2, 'vertices': 2,
                'chunks': [descriptor(0, 10), descriptor(1, 10)]}
    with pytest.raises(FastPrepareError, match='Duplicate morphology across chunks'):
        list(iter_prepared_chunks(metadata, audited_sources=sources, params=None, limit=1))
    metadata['chunks'] = [descriptor(0, 10)]
    metadata['vertices'] = 1
    with pytest.raises(FastPrepareError, match='Incomplete geometry snapshot'):
        list(iter_prepared_chunks(metadata, audited_sources=sources, params=None, limit=1))


def test_manifest_rejects_unreviewed_producer(tmp_path, monkeypatch):
    from service.infrastructure.stimulation.geometry_cache import cache

    manifest = {'format': 'malecns-packed-geometry-cache-v1', 'chunks': [{}], 'vertices': 1,
                'producer_sha256': 'a' * 64}
    data = json.dumps(manifest).encode('utf8')
    (tmp_path / 'manifest.json').write_bytes(data)
    manifest_hash = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(cache, '_producer_sha256', lambda: 'b' * 64)
    with pytest.raises(FastPrepareError, match='producer'):
        read_manifest(tmp_path, expected_manifest_sha256=manifest_hash)
    monkeypatch.setattr(cache, '_producer_sha256', lambda: 'a' * 64)
    assert read_manifest(tmp_path, expected_manifest_sha256=manifest_hash)['vertices'] == 1
