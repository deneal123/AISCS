import hashlib
import json

import numpy as np
import pytest

from service.infrastructure.connectome.morphology_repository import BASE
from service.infrastructure.stimulation.experimental_fused_gpu import experimental_summaries, pack
from service.infrastructure.stimulation.network_field import _gpu_batch, _prepare_gpu_skeleton
from tests.test_packed_geometry_chunk import sources  # noqa: F401


@pytest.mark.parametrize('current,conductivity', [(0., .3), (1e-9, .3), (-300., .3), (100., 10.)])
@pytest.mark.parametrize('source,target', [([0., 10., 0.], [50., 10., 0.]),
                                          ([.804, .016, .024], [50., 10., 0.])])
def test_fused_matches_existing_gpu_or_falls_back(
    sources, current, conductivity, source, target,  # noqa: F811
):
    from numba import cuda

    if not cuda.is_available():
        pytest.skip('CUDA toolkit and device are not available')
    entries, _ = sources
    expected = _gpu_batch(entries, source, target, current, conductivity, 1., True)
    observed, fallbacks = experimental_summaries(entries, source, target, current, conductivity,
                                                 clearance_um=1., allow_degenerate=True)
    assert 0 <= fallbacks <= len(entries)
    for a, b in zip(expected, observed, strict=True):
        a, b = a.copy(), b.copy()
        x = a.pop('max_abs_curvature_signed_mv_per_um2', None)
        y = b.pop('max_abs_curvature_signed_mv_per_um2', None)
        assert a == b
        assert (x is None) == (y is None)
        if x is not None:
            assert np.isclose(x, y, rtol=1e-9, atol=1e-12)


def test_invalid_controls_rejected_before_gpu():
    with pytest.raises(ValueError):
        experimental_summaries([], [0, 0, 0], [10, 0, 0], 1., .3,
                               clearance_um=1., allow_degenerate='false')
    with pytest.raises(ValueError):
        experimental_summaries([], [0, 0, 0], [10, 0, 0], 1., .3, clearance_um=0.)


def test_large_vertex_id_cannot_be_silently_truncated(sources):  # noqa: F811
    entries, _ = sources
    entry = entries[0].copy()
    ids, points, parents, radii = entry['geometry']
    ids = ids.copy()
    ids[0] = 2**31 + 1
    entry['geometry'] = ids, points, parents, radii
    with pytest.raises(ValueError, match='geometry'):
        pack([entry])


@pytest.mark.parametrize('allow_degenerate', [False, True])
@pytest.mark.parametrize('offset', [-1e-11, 0., 1e-11, 1e-4])
def test_fused_geometry_edges_and_contact_boundaries(tmp_path, allow_degenerate, offset):
    from numba import cuda

    if not cuda.is_available():
        pytest.skip('CUDA toolkit and device are not available')
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'receipts').mkdir()
    geometries = [
        b'1 0 0 0 0 1 -1\n2 0 125 0 0 1 1\n3 0 250 0 0 1 2\n',
        b'1 0 0 0 0 1 -1\n2 0 0 0 0 1 1\n3 0 250 0 0 1 2\n',
        b'1 0 0 0 0 1 -1\n',
        b'1 0 0 0 0 1 -1\n2 0 125 0 0 1 1\n3 0 125 125 0 1 1\n',
    ]
    entries = []
    for body, raw in enumerate(geometries, start=31):
        (tmp_path / f'raw/{body}.swc').write_bytes(raw)
        receipt = {'body_id': body, 'url': BASE + f'{body}.swc',
                   'sha256': hashlib.sha256(raw).hexdigest()}
        (tmp_path / f'receipts/{body}.json').write_text(json.dumps(receipt))
        entries.append(_prepare_gpu_skeleton((body, [tmp_path])))
    assert all('geometry' in entry for entry in entries)
    source, target = [1., 1.008 + offset, 0.], [50., 10., 0.]
    expected = _gpu_batch(entries, source, target, -300., .3, 1., allow_degenerate)
    actual, _ = experimental_summaries(entries, source, target, -300., .3,
                                        clearance_um=1., allow_degenerate=allow_degenerate)
    for before, after in zip(expected, actual, strict=True):
        before, after = before.copy(), after.copy()
        x = before.pop('max_abs_curvature_signed_mv_per_um2', None)
        y = after.pop('max_abs_curvature_signed_mv_per_um2', None)
        assert before == after
        assert (x is None) == (y is None)
        if x is not None:
            assert np.isclose(x, y, rtol=1e-9, atol=1e-12)
