import math

import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.tree_levels import (
    batch_children_csr,
    batch_parent_groups,
    children_csr,
    parent_groups_by_level,
)


def test_groups_preserve_edges_and_give_each_parent_one_writer():
    parents = [-1, 0, 0, 1, 1, 2, 4]
    levels = parent_groups_by_level(parents)
    assert levels == [[(0, (1, 2))], [(1, (3, 4)), (2, (5,))], [(4, (6,))]]
    children = sorted(child for level in levels for _, group in level for child in group)
    assert children == list(range(1, 7))
    assert all(len({parent for parent, _ in level}) == len(level) for level in levels)


def test_reverse_level_elimination_matches_sequential_tree_solve():
    parents = [-1, 0, 0, 1, 1, 2, 4]
    conductance = [0, .2, .3, .4, .5, .6, .7]
    diagonal = [3., 4., 5., 6., 7., 8., 9.]
    rhs = [1., 2., 3., 4., 5., 6., 7.]
    expected_d, expected_r = diagonal.copy(), rhs.copy()
    for node in range(len(parents) - 1, 0, -1):
        p, g = parents[node], conductance[node]
        expected_d[p] -= g * g / expected_d[node]
        expected_r[p] += g * expected_r[node] / expected_d[node]
    actual_d, actual_r = diagonal.copy(), rhs.copy()
    for level in reversed(parent_groups_by_level(parents)):
        for parent, children in level:
            actual_d[parent] -= sum(conductance[c] ** 2 / actual_d[c] for c in children)
            actual_r[parent] += sum(conductance[c] * actual_r[c] / actual_d[c] for c in children)
    assert all(math.isclose(a, b, rel_tol=1e-14) for a, b in zip(actual_d, expected_d, strict=True))
    assert all(math.isclose(a, b, rel_tol=1e-14) for a, b in zip(actual_r, expected_r, strict=True))


@pytest.mark.parametrize('parents', [[], [0], [True], [-1, 1], [-1, -1], [-1, True], [-1, 0, 3]])
def test_invalid_tree_is_rejected(parents):
    with pytest.raises(ValueError):
        parent_groups_by_level(parents)


def test_single_root_has_no_work():
    assert parent_groups_by_level([-1]) == []


def test_children_csr_covers_edges_and_leaves():
    parents = [-1, 0, 0, 1, 1, 2, 4]
    offsets, indices = children_csr(parents)
    assert offsets == [0, 2, 4, 5, 5, 6, 6, 6]
    assert indices == [1, 2, 3, 4, 5, 6]
    assert all(parents[child] == node for node in range(len(parents))
               for child in indices[offsets[node]:offsets[node + 1]])
    assert children_csr([-1]) == ([0, 0], [])


@pytest.mark.parametrize('parents', [[], [0], [True], [-1, 1], [-1, -1], [-1, True]])
def test_children_csr_rejects_invalid_tree(parents):
    with pytest.raises(ValueError):
        children_csr(parents)


def test_batch_csr_keeps_heterogeneous_trees_independent():
    trees = [[-1, 0, 0, 1], [-1], [-1, 0, 1]]
    offsets, indices = batch_children_csr(trees)
    for cell, parents in enumerate(trees):
        for node in range(len(parents)):
            start, end = offsets[node][cell], offsets[node + 1][cell]
            assert [indices[i][cell] for i in range(start, end)] == [
                i for i in range(1, len(parents)) if parents[i] == node
            ]
    with pytest.raises(ValueError):
        batch_children_csr([])
    assert batch_children_csr([[-1], [-1]]) == ([[0, 0], [0, 0]], [[0, 0]])


def test_batch_levels_reconstruct_heterogeneous_trees():
    trees = [[-1, 0, 0, 1, 1, 2, 4], [-1], [-1, 0, 1]]
    bounds, parents, offsets, children, counts = batch_parent_groups(trees)
    for cell, tree in enumerate(trees):
        reconstructed = []
        for level in range(counts[cell]):
            groups = []
            for group in range(bounds[level][cell], bounds[level + 1][cell]):
                group_children = tuple(children[i][cell] for i in range(
                    offsets[group][cell], offsets[group + 1][cell]))
                groups.append((parents[group][cell], group_children))
            reconstructed.append(groups)
        assert reconstructed == parent_groups_by_level(tree)
    with pytest.raises(ValueError):
        batch_parent_groups([])
    bounds, parents, offsets, children, counts = batch_parent_groups([[-1], [-1]])
    assert counts == [0, 0]
    assert bounds == parents == offsets == children == [[0, 0]]


def test_random_batches_preserve_tree_topology():
    rng = np.random.default_rng(20261110)
    for _ in range(20):
        trees = []
        for size in rng.integers(1, 48, size=8):
            trees.append([-1] + [int(rng.integers(node)) for node in range(1, size)])
        bounds, parents, offsets, children, counts = batch_parent_groups(trees)
        csr_offsets, csr_children = batch_children_csr(trees)
        for cell, tree in enumerate(trees):
            expected = parent_groups_by_level(tree)
            assert counts[cell] == len(expected)
            for level, groups in enumerate(expected):
                start, end = bounds[level][cell], bounds[level + 1][cell]
                actual = [
                    (parents[group][cell], tuple(
                        children[i][cell]
                        for i in range(offsets[group][cell], offsets[group + 1][cell])
                    ))
                    for group in range(start, end)
                ]
                assert actual == groups
            for node in range(len(tree)):
                start, end = csr_offsets[node][cell], csr_offsets[node + 1][cell]
                assert [csr_children[i][cell] for i in range(start, end)] == [
                    child for child in range(1, len(tree)) if tree[child] == node
                ]


def test_csr_incident_conductance_and_currents_match_edge_accumulation():
    rng = np.random.default_rng(20261110)
    trees = [[-1] + [int(rng.integers(node)) for node in range(1, size)]
             for size in (1, 4, 17, 32)]
    offsets, children = batch_children_csr(trees)
    for cell, tree in enumerate(trees):
        size = len(tree)
        conductance = rng.uniform(.01, .2, size)
        voltage = rng.normal(size=size)
        expected_diagonal = np.zeros(size)
        expected_current = np.zeros(size)
        for node in range(1, size):
            parent = tree[node]
            flow = conductance[node] * (voltage[node] - voltage[parent])
            expected_diagonal[node] += conductance[node]
            expected_diagonal[parent] += conductance[node]
            expected_current[node] -= flow
            expected_current[parent] += flow
        diagonal = np.zeros(size)
        current = np.zeros(size)
        for node in range(size):
            if node:
                diagonal[node] += conductance[node]
                current[node] -= conductance[node] * (voltage[node] - voltage[tree[node]])
            for index in range(offsets[node][cell], offsets[node + 1][cell]):
                child = children[index][cell]
                diagonal[node] += conductance[child]
                current[node] += conductance[child] * (voltage[child] - voltage[node])
        np.testing.assert_allclose(diagonal, expected_diagonal, atol=1e-15)
        np.testing.assert_allclose(current, expected_current, atol=1e-15)


def test_grouped_elimination_solves_independent_tree_matrices():
    rng = np.random.default_rng(20261109)
    for size in (2, 7, 31):
        for _ in range(5):
            parents = [-1] + [int(rng.integers(0, node)) for node in range(1, size)]
            conductance = np.r_[0., rng.uniform(.01, .2, size - 1)]
            diagonal = rng.uniform(2., 3., size)
            rhs = rng.normal(size=size)
            matrix = np.diag(diagonal)
            for node in range(1, size):
                matrix[node, parents[node]] = matrix[parents[node], node] = -conductance[node]
            expected = np.linalg.solve(matrix, rhs)
            reduced_d, reduced_r = diagonal.copy(), rhs.copy()
            for level in reversed(parent_groups_by_level(parents)):
                for parent, children in level:
                    reduced_d[parent] -= sum(conductance[c] ** 2 / reduced_d[c] for c in children)
                    reduced_r[parent] += sum(
                        conductance[c] * reduced_r[c] / reduced_d[c] for c in children)
            result = np.empty(size)
            result[0] = reduced_r[0] / reduced_d[0]
            for node in range(1, size):
                result[node] = (
                    reduced_r[node] + conductance[node] * result[parents[node]]) / reduced_d[node]
            np.testing.assert_allclose(result, expected, rtol=1e-12, atol=1e-12)
