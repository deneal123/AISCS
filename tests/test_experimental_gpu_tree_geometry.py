import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.tree_geometry import refined_tree


def test_refined_tree_preserves_segment_resistances():
    edges = [(2, 1), (3, 2)]
    parents, conductance, segments = refined_tree(edges, [2., 4., 8., 10.], [6., 12.],
                                                  {2: 3, 3: 1})
    assert len(parents) == 7
    assert parents[0] == -1
    assert sorted(conductance[1:]) == sorted([1 / x for x in (2., 4., 8., 10., 6., 12.)])
    assert len(set(segments)) == 4
    assert all(0 <= parent < node for node, parent in enumerate(parents) if node)
    assert np.isfinite(conductance).all()


def test_forest_has_zero_conductance_only_at_segment_roots():
    parents, conductance, segments = refined_tree(
        [(2, 1), (4, 3)], [1., 2.], [1., 2.], {2: 1, 4: 1}, allow_forest=True)
    roots = np.flatnonzero(conductance[1:] == 0) + 1
    assert len(roots) == 1
    assert roots[0] in segments and parents[roots[0]] == 0


def test_many_components_preserve_input_order():
    edges = [(2 * i + 2, 2 * i + 1) for i in range(1000)]
    parents, conductance, segments = refined_tree(
        edges, [1.] * len(edges), [2.] * len(edges),
        {child: 1 for child, _ in edges}, allow_forest=True)
    assert len(segments) == len(edges)
    assert np.all(np.diff(segments) > 0)
    assert np.count_nonzero(conductance == 0) == len(edges)
    assert all(parents[segment] == 0 for segment in segments[1:])


@pytest.mark.parametrize(('edges', 'parent', 'child', 'counts'), [
    ([], [], [], {}),
    ([(2, 1)], [0.], [1.], {2: 1}),
    ([(2, 1)], [1.], [1.], {2: 2}),
    ([(2, 1), (3, 4)], [1., 1.], [1., 1.], {2: 1, 3: 1}),
    ([(2, 1), (1, 2)], [1., 1.], [1., 1.], {2: 1, 1: 1}),
])
def test_refined_tree_rejects_invalid_cables(edges, parent, child, counts):
    with pytest.raises(ValueError):
        refined_tree(edges, parent, child, counts)
