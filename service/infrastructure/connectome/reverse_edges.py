"""Transient reverse adjacency for repeated full-graph feedback mapping."""

import numpy as np
from numba import njit


@njit(cache=True)
def _count_targets(posts, offsets):
    for target in posts:
        if target < 0 or target >= len(offsets) - 1:
            raise ValueError('Graph contains an invalid target index')
        offsets[target + 1] += 1
    for target in range(1, len(offsets)):
        offsets[target] += offsets[target - 1]


@njit(cache=True)
def _fill_edges(posts, cursors, edges):
    for edge, target in enumerate(posts):
        edges[cursors[target]] = edge
        cursors[target] += 1


class ReverseEdges:
    """Index CSR edge numbers by target, preserving original edge order.

    The graph must remain unchanged for this object's lifetime. Memory is one
    uint32 per edge when possible, plus two int64 arrays per graph node.
    """

    def __init__(self, graph):
        self.graph = graph
        self.offsets = np.zeros(len(graph.ids) + 1, dtype=np.int64)
        _count_targets(graph.posts, self.offsets)
        dtype = np.uint32 if len(graph.posts) <= np.iinfo(np.uint32).max else np.uint64
        self.edges = np.empty(len(graph.posts), dtype=dtype)
        cursors = self.offsets[:-1].copy()
        _fill_edges(graph.posts, cursors, self.edges)

    def incoming(self, body_ids):
        if (not isinstance(body_ids, (list, tuple)) or not body_ids
                or any(type(body) is not int or body <= 0 for body in body_ids)
                or len(set(body_ids)) != len(body_ids)):
            raise ValueError('Invalid incoming target batch')
        positions = np.searchsorted(self.graph.ids, body_ids)
        if any(pos >= len(self.graph.ids) or int(self.graph.ids[pos]) != body
               for pos, body in zip(positions, body_ids, strict=True)):
            raise KeyError('Neuron is not in the registered graph')
        return {body: self.edges[self.offsets[pos]:self.offsets[pos + 1]]
                for body, pos in zip(body_ids, positions, strict=True)}
