import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.packing import pack_trees
from service.infrastructure.stimulation.experimental_gpu.tree_levels import (
    batch_children_csr,
    batch_parent_groups,
    batch_tree_layouts,
)


def test_packs_different_trees_with_reversible_node_segment_mapping():
    trees = [([-1, 0, 1], [0., .5, .3], [0, 2]), ([-1, 0], [0., .7], [1])]
    packed = pack_trees(trees)
    np.testing.assert_array_equal(packed.lengths, [2, 1])
    np.testing.assert_array_equal(packed.nodes, [3, 2])
    for cell, (parents, conductances, segments) in enumerate(trees):
        np.testing.assert_array_equal(packed.parents[:len(parents), cell], parents)
        np.testing.assert_array_equal(packed.conductances[:len(parents), cell], conductances)
        np.testing.assert_array_equal(packed.segment_nodes[:len(segments), cell], segments)
        np.testing.assert_array_equal(
            packed.node_segments[segments, cell], np.arange(len(segments)))
    assert packed.node_segments[2, 1] == -1


def test_many_disconnected_components_require_segment_roots():
    parents = [-1] + [0] * 999
    conductances = [0.] * 1000
    segments = list(range(1000))
    packed = pack_trees([(parents, conductances, segments)])
    np.testing.assert_array_equal(packed.segment_nodes[:, 0], segments)
    with pytest.raises(ValueError, match='component root'):
        pack_trees([(parents, conductances, segments[:-1])])


def test_combined_layout_matches_separate_layouts():
    trees = [[-1, 0, 0, 1, 1, 4], [-1], [-1, 0, 1, 2]]
    parent, children = batch_tree_layouts(trees)
    assert parent == batch_parent_groups(trees)
    assert children == batch_children_csr(trees)
    array_parent, array_children = batch_tree_layouts(trees, as_arrays=True)
    for expected, actual in zip(parent, array_parent, strict=True):
        np.testing.assert_array_equal(actual, expected)
    for expected, actual in zip(children, array_children, strict=True):
        np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize('tree', [
    ([-1, 0], [0., 0.], [1]),
    ([-1, 0], [0., float('nan')], [1]),
    ([-1, 0], [0., .2], [1, 1]),
    ([-1, 1], [0., .2], [1]),
    ([-1, 0], [0., .2], [2]),
    ([-1., 0.], [0., .2], [1]),
])
def test_rejects_invalid_trees(tree):
    with pytest.raises(ValueError):
        pack_trees([tree])
