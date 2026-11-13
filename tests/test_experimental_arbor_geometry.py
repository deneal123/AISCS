from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_arbor.geometry import (
    map_edge_volumes,
    map_probe_columns,
)


def cable(branch, prox, dist):
    return SimpleNamespace(branch=branch, prox=prox, dist=dist)


class ControlVolumes:
    num_cv = 4

    def cables(self, index):
        return [[cable(0, 0., .5)], [cable(0, .5, .5)],
                [cable(0, .5, 1.)], [cable(1, 0., 1.)]][index]


class ArborFixture:
    def __init__(self, overlaps):
        self.overlaps = overlaps

    def cv_data(self, cell):
        return ControlVolumes()

    def intersect_region(self, tag, cv, metric):
        assert metric == 'area'
        return self.overlaps[tag]


def test_edge_mapping_is_unique_and_preserves_requested_order():
    backend = ArborFixture({'(tag 10)': [(0, 1.)], '(tag 20)': [(2, 1.)]})
    cv, indices = map_edge_volumes(backend, object(), np.array([20, 10], dtype=np.int64))
    assert isinstance(cv, ControlVolumes)
    np.testing.assert_array_equal(indices, [2, 0])


@pytest.mark.parametrize('ids', [[], [10, 10], [True], ['10'], [0], [2**31]])
def test_invalid_tagged_edges_are_rejected(ids):
    with pytest.raises(ValueError, match='edge IDs'):
        map_edge_volumes(ArborFixture({}), object(), ids)


@pytest.mark.parametrize('overlap', [[], [(0, .9)], [(0, .5), (2, .5)],
                                     [(5, 1.)], [(0, float('nan'))]])
def test_incomplete_ambiguous_or_invalid_volume_is_rejected(overlap):
    with pytest.raises(ValueError):
        map_edge_volumes(ArborFixture({'(tag 10)': overlap}), object(), [10])


def test_distinct_edges_cannot_silently_share_a_volume():
    backend = ArborFixture({'(tag 10)': [(0, 1.)], '(tag 20)': [(0, 1.)]})
    with pytest.raises(ValueError, match='same volume'):
        map_edge_volumes(backend, object(), [10, 20])


def test_probe_mapping_uses_geometry_not_input_order_and_skips_forks():
    metadata = [cable(0, .5, 1.), cable(0, .5, .5), cable(0, 0., .5), cable(1, 0., 1.)]
    actual = map_probe_columns(ControlVolumes(), [0, 2, 3], metadata)
    np.testing.assert_array_equal(actual, [2, 0, 3])


@pytest.mark.parametrize('metadata', [
    [cable(0, 0., .5), cable(0, 0., .5)],
    [cable(0, .5, 1.)],
    [cable(0, 0., .5000000000001)],
    [cable(0, 0., float('nan'))],
    [cable(-1, 0., .5)],
])
def test_ambiguous_missing_or_invalid_probe_cables_are_rejected(metadata):
    with pytest.raises(ValueError):
        map_probe_columns(ControlVolumes(), [0], metadata)


@pytest.mark.parametrize('indices', [[], [0, 0], [-1], [4], [True], [0.5]])
def test_invalid_volume_indices_are_rejected(indices):
    with pytest.raises(ValueError, match='volume'):
        map_probe_columns(ControlVolumes(), indices, [cable(0, 0., .5)])


def test_zero_area_fork_cannot_be_treated_as_neuron_segment():
    with pytest.raises(ValueError, match='missing or ambiguous'):
        map_probe_columns(ControlVolumes(), [1], [cable(0, .5, .5)])
