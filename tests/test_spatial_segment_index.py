import numpy as np
import pytest

from service.infrastructure.connectome.spatial_segment_index import SegmentCandidateIndex
from service.infrastructure.connectome.synapse_morphology import _nearest_prepared_segments


def exhaustive_distance2(starts, vectors, length2, point):
    delta = point - starts
    fraction = np.clip(np.einsum('ij,ij->i', delta, vectors) / length2, 0, 1)
    residual = delta - fraction[:, None] * vectors
    return np.einsum('ij,ij->i', residual, residual)


def test_candidates_contain_every_exhaustive_nearest_and_tie():
    rng = np.random.default_rng(836)
    starts = rng.uniform(-200, 200, (3000, 3))
    # Mixed lengths include long segments whose midpoint is far from a query.
    vectors = rng.normal(size=(len(starts), 3)) * rng.lognormal(0, 2, (len(starts), 1))
    starts[1] = starts[0]
    vectors[1] = vectors[0]
    length2 = np.einsum('ij,ij->i', vectors, vectors)
    index = SegmentCandidateIndex(starts, vectors, length2)
    points = np.vstack((rng.uniform(-250, 250, (100, 3)), starts[0], starts[0] + vectors[0]))
    for point in points:
        distance2 = exhaustive_distance2(starts, vectors, length2, point)
        expected = set(np.flatnonzero(np.isclose(distance2, distance2.min(),
                                                  rtol=1e-12, atol=1e-18)))
        candidates = index.candidates(point)
        assert expected.issubset(set(candidates))
        assert np.all(candidates[1:] > candidates[:-1])


def test_rejects_invalid_geometry_and_nonfinite_queries():
    with pytest.raises(ValueError, match='Invalid segments'):
        SegmentCandidateIndex([[0, 0, 0]], [[0, 0, 0]], [0])
    with pytest.raises(ValueError, match='segment bounds'):
        SegmentCandidateIndex([[0, 0, 0]], [[100, 0, 0]], [1])
    index = SegmentCandidateIndex([[0, 0, 0]], [[1, 0, 0]], [1])
    with pytest.raises(ValueError, match='Invalid query'):
        index.candidates([np.nan, 0, 0])
    with np.errstate(over='ignore', invalid='ignore'):
        with pytest.raises(ValueError, match='Non-finite'):
            index.candidates([1e308, 0, 0])


def test_pruned_projection_matches_existing_exhaustive_mapping():
    rng = np.random.default_rng(431)
    starts = rng.uniform(-80, 80, (1200, 3))
    vectors = rng.normal(size=(len(starts), 3)) * rng.lognormal(0, 1.5, (len(starts), 1))
    starts[1], vectors[1] = starts[0], vectors[0]
    length2 = np.einsum('ij,ij->i', vectors, vectors)
    radii = rng.uniform(.01, 2, (len(starts), 2))
    ids = np.arange(10, len(starts) + 10)
    prepared = (ids.tolist(), starts, radii, vectors, length2)
    index = SegmentCandidateIndex(starts, vectors, length2)
    points = np.vstack((rng.uniform(-100, 100, (60, 3)), starts[0]))
    expected = _nearest_prepared_segments(prepared, points, point_batch_size=7)
    for offset, point in enumerate(points):
        selected = index.candidates(point)
        subset = (ids[selected].tolist(), starts[selected], radii[selected], vectors[selected],
                  length2[selected])
        actual = _nearest_prepared_segments(subset, [point])
        assert actual['child_node_ids'][0] == expected['child_node_ids'][offset]
        for key in ('segment_fractions', 'centerline_distances_um', 'interpolated_swc_radii_um'):
            assert actual[key][0] == pytest.approx(expected[key][offset], abs=1e-12, rel=1e-12)
