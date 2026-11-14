from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.connectome.neighbors import incoming_edge_indices_many
from service.infrastructure.connectome.reverse_edges import ReverseEdges


def test_reverse_edges_match_original_order_and_empty_targets():
    rng = np.random.default_rng(42)
    ids = np.arange(1, 102, dtype=np.int64)
    posts = rng.integers(0, 100, size=10000, dtype=np.int32)
    graph = SimpleNamespace(ids=ids, posts=posts)
    index = ReverseEdges(graph)
    targets = [101, 7, 2, 99]
    expected = incoming_edge_indices_many(graph, targets, block_size=137)
    actual = index.incoming(targets)
    for target in targets:
        np.testing.assert_array_equal(actual[target], expected[target])
    assert actual[101].size == 0
    assert index.edges.dtype == np.uint32
    with pytest.raises(KeyError):
        index.incoming([999])
    with pytest.raises(ValueError):
        index.incoming([1, 1])


@pytest.mark.parametrize('posts', [[-1], [2]])
def test_reverse_edges_rejects_invalid_graph_indices(posts):
    graph = SimpleNamespace(ids=np.array([1, 2]), posts=np.array(posts))
    with pytest.raises(ValueError, match='invalid target'):
        ReverseEdges(graph)
