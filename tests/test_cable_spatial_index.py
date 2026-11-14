import numpy as np
import pytest

from service.infrastructure.connectome.cable_spatial_index import CableSpatialIndex
from service.infrastructure.connectome.synapse_morphology import (
    _nearest_prepared_segments,
    _prepare_segments,
    prepare_cached_segments,
)
from service.infrastructure.stimulation.geometry_cache.chunk import _RECORD


def test_index_matches_exhaustive_random_and_equal_distance_candidates():
    rng = np.random.default_rng(52)
    starts = rng.normal(size=(500, 3)) * 5
    vectors = rng.normal(size=(500, 3))
    starts[1], vectors[1] = starts[0], vectors[0]
    radii = rng.uniform(.1, 1., size=(500, 2))
    ids = list(range(1, 501))
    lengths2 = np.einsum('ij,ij->i', vectors, vectors)
    prepared = (ids, starts, radii, vectors, lengths2)
    points = np.vstack([rng.normal(size=(100, 3)) * 6, starts[0], starts[0] + vectors[0] / 2])
    expected = _nearest_prepared_segments(prepared, points)
    actual = CableSpatialIndex(prepared).query(points)
    assert actual['child_node_ids'] == expected['child_node_ids']
    for key in ('segment_fractions', 'centerline_distances_um', 'interpolated_swc_radii_um'):
        np.testing.assert_allclose(actual[key], expected[key], rtol=1e-11, atol=1e-12)


def test_index_preserves_chunked_nontransitive_ties():
    count = 4097
    starts = np.zeros((count, 3))
    starts[:, 0] = -1
    starts[:, 1] = 100
    vectors = np.tile([2., 0., 0.], (count, 1))
    starts[[0, 2048, 4096], 1] = np.sqrt([1 + 1.5e-12, 1 + .75e-12, 1.])
    prepared = (np.arange(1, count + 1), starts, np.ones((count, 2)),
                vectors, np.full(count, 4.))
    point = np.zeros((1, 3))
    expected = _nearest_prepared_segments(prepared, point)
    actual = CableSpatialIndex(prepared).query(point)
    assert actual == expected


def test_cached_geometry_matches_swc_cable_candidates():
    swc = '3 3 250 0 0 10 1\n1 1 0 0 0 20 -1\n2 3 0 250 0 15 1\n'
    records = np.array([(2., 0., 0., .08, 1, 3), (0., 0., 0., .16, -1, 1),
                        (0., 2., 0., .12, 1, 2)], dtype=_RECORD)
    points = np.array([[.1, 1., 0.], [1., .2, 0.]])
    expected = _nearest_prepared_segments(_prepare_segments(swc), points)
    actual = CableSpatialIndex(prepare_cached_segments(records)).query(points)
    assert actual == expected
    broken = records.copy()
    broken[0]['parent'] = 0
    with pytest.raises(ValueError, match='segments'):
        prepare_cached_segments(broken)
