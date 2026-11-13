from __future__ import annotations

import numpy as np

from service.infrastructure.stimulation.experimental_gpu.reroot_tree import (
    centre_levels, reroot_centre)


def _chain():
    """A straight cable: one segment at the root, the rest interior."""
    parents = [-1, 0, 1, 2]
    conductances = [0.0, 3.0, 2.0, 1.0]
    segments = [0, 1, 2, 3]
    return (np.asarray(parents, np.int64), np.asarray(conductances, np.float64),
            np.asarray(segments, np.int64))


def _star():
    """Soma with three arms of length two."""
    parents = np.asarray([-1, 0, 1, 0, 3, 0, 5], np.int64)
    conductances = np.asarray([0.0, 4.0, 3.0, 4.0, 3.0, 4.0, 3.0], np.float64)
    segments = np.asarray([0, 1, 2, 3, 4, 5, 6], np.int64)
    return parents, conductances, segments


def test_reroot_keeps_every_edge_and_keeps_the_tree_rooted():
    for parents, conductances, segments in (_chain(), _star()):
        new_parents, new_conductances, new_segments = reroot_centre(
            parents, conductances, segments)
        assert new_parents[0] == -1
        assert new_parents.size == parents.size
        assert np.all(new_parents[1:] < np.arange(1, parents.size))
        # Re-orientation is a RELABELLING: the multiset of axial conductances is
        # invariant (the root contributes a structural zero).
        assert np.allclose(np.sort(new_conductances), np.sort(conductances))
        assert np.all(new_conductances[new_parents >= 0] > 0.0)


def test_reroot_preserves_the_segment_count_and_never_repeats_a_node():
    parents, conductances, segments = _star()
    _p, _c, new_segments = reroot_centre(parents, conductances, segments)
    assert new_segments.size == segments.size
    assert np.unique(new_segments).size == segments.size
    assert np.all(new_segments >= 0) and np.all(new_segments < parents.size)


def test_reroot_shallows_a_soma_rooted_star():
    parents, conductances, segments = _star()
    new_parents, _c, _s = reroot_centre(parents, conductances, segments)
    # Soma-rooted depth is 3 (soma -> arm middle -> arm tip).
    assert centre_levels(parents) <= 2
    depth = np.zeros(parents.size, np.int64)
    for node in range(1, parents.size):
        depth[node] = depth[new_parents[node]] + 1
    assert int(depth.max()) <= 2


def test_reroot_is_idempotent_in_height():
    parents, conductances, segments = _star()
    once = reroot_centre(parents, conductances, segments)
    twice = reroot_centre(*once)
    depth = np.zeros(parents.size, np.int64)
    for node in range(1, parents.size):
        depth[node] = depth[twice[0][node]] + 1
    depth_one = np.zeros(parents.size, np.int64)
    for node in range(1, parents.size):
        depth_one[node] = depth_one[once[0][node]] + 1
    assert int(depth.max()) == int(depth_one.max())


def test_reroot_leaves_a_degenerate_tree_alone():
    parents = np.asarray([-1, 0], np.int64)
    conductances = np.asarray([0.0, 5.0], np.float64)
    segments = np.asarray([0, 1], np.int64)
    new_parents, new_conductances, new_segments = reroot_centre(
        parents, conductances, segments)
    assert np.array_equal(new_parents, parents)
    assert np.array_equal(new_conductances, conductances)
    assert np.array_equal(new_segments, segments)