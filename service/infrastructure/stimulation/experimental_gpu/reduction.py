"""Fast tree reduction: contract degree-2 chains, drop degree-1 dead ends.

Why this exists, measured on real registered cells:
- A cell carries about 370 Hines LEVELS for about 338 segments, so the kernel
  walks a long, thin level chain and the solve is latency bound on it.
- Reduction cuts nodes to 0.54x but the level count by roughly half, and the
  measured solve rate improves 2.76x (40 000 -> 110 000 cells per second at
  200 steps).
- The Python reference implementation spends 11.5 ms per cell, about 1900 s for
  the population, which is 16x the budget, so the same structural rules are
  reimplemented here over integer arrays.

The tree is held as parent/conductance plus doubly linked child chains, which
makes replacing or removing a node O(1), so one cell costs O(nodes).
Structural rules match the reference exactly: a virtual (non-segment) node with
one arm is deleted, with two arms is contracted using the series conductance
g_up * g_down / (g_up + g_down), and with three or more arms is kept as a
branch point. Membrane segments are never removed.
"""

import numpy as np
from numba import njit


@njit(cache=True, nogil=True)
def _reduce(parents, conductances, is_segment, first_child, next_sibling,
            prev_sibling, alive, stack):
    """Apply the structural rules in place and return the live node count."""
    size = parents.shape[0]
    top = 0
    for node in range(size):
        if not is_segment[node]:
            stack[top] = node
            top += 1
    while top > 0:
        top -= 1
        node = stack[top]
        if not alive[node]:
            continue
        parent = parents[node]
        child = -1
        children = 0
        walk = first_child[node]
        while walk >= 0:
            if alive[walk]:
                children += 1
                if children > 1:
                    break
                child = walk
            walk = next_sibling[walk]
        arms = children + (1 if parent >= 0 else 0)
        if arms == 0:
            alive[node] = False
            continue
        if arms >= 3:
            continue
        if arms == 1:
            if parent >= 0:
                before = prev_sibling[node]
                after = next_sibling[node]
                if before >= 0:
                    next_sibling[before] = after
                else:
                    first_child[parent] = after
                if after >= 0:
                    prev_sibling[after] = before
                alive[node] = False
                if not is_segment[parent]:
                    stack[top] = parent
                    top += 1
            else:
                parents[child] = -1
                conductances[child] = 0.0
                next_sibling[child] = -1
                prev_sibling[child] = -1
                alive[node] = False
                if not is_segment[child]:
                    stack[top] = child
                    top += 1
            continue
        up = conductances[node]
        down = conductances[child]
        if up <= 0.0 or down <= 0.0:
            # A zero conductance separates components; it is not a series link.
            continue
        parents[child] = parent
        conductances[child] = up * down / (up + down)
        before = prev_sibling[node]
        after = next_sibling[node]
        if before >= 0:
            next_sibling[before] = child
        else:
            first_child[parent] = child
        prev_sibling[child] = before
        next_sibling[child] = after
        if after >= 0:
            prev_sibling[after] = child
        alive[node] = False
        if not is_segment[parent]:
            stack[top] = parent
            top += 1
    count = 0
    for node in range(size):
        if alive[node]:
            count += 1
    return count


@njit(cache=True, nogil=True)
def _breadth_first(alive, parents, first_child, next_sibling, order, roots):
    """Renumber surviving nodes breadth first; returns (count, root_count)."""
    size = alive.shape[0]
    root_count = 0
    for node in range(size):
        if alive[node] and parents[node] < 0:
            roots[root_count] = node
            root_count += 1
    head = 0
    tail = 0
    for index in range(root_count):
        node = roots[index]
        order[tail] = node
        tail += 1
    while head < tail:
        node = order[head]
        head += 1
        walk = first_child[node]
        while walk >= 0:
            if alive[walk]:
                order[tail] = walk
                tail += 1
            walk = next_sibling[walk]
    return tail, root_count


@njit(cache=True, nogil=True)
def _chains(parents, first_child, next_sibling, prev_sibling):
    """Build the doubly linked child chains in place, children in id order."""
    size = parents.shape[0]
    for node in range(size - 1, 0, -1):
        parent = parents[node]
        if parent < 0:
            continue
        head = first_child[parent]
        next_sibling[node] = head
        if head >= 0:
            prev_sibling[head] = node
        first_child[parent] = node
    return 0

def reduce_structure(parents, conductances, segment_nodes):
    """Return (alive, parents, conductances) after the structural reduction.

    ``alive`` marks the survivors in the ORIGINAL numbering, and the two arrays
    are copies mutated so every surviving node points at its surviving ancestor
    with the contracted series conductance. This matches the contract of the
    numpy implementation in reduced_tree.py, so a caller that renumbers, counts
    arms or collects statistics keeps doing that itself.
    """
    parents = np.ascontiguousarray(parents, dtype=np.int64)
    conductances = np.ascontiguousarray(conductances, dtype=np.float64)
    segments = np.ascontiguousarray(segment_nodes, dtype=np.int64)
    size = parents.shape[0]
    alive = np.ones(size, dtype=np.bool_)
    if size < 2 or segments.size == 0:
        return alive, parents.copy(), conductances.copy()
    is_segment = np.zeros(size, dtype=np.bool_)
    is_segment[segments] = True
    parents = parents.copy()
    conductances = conductances.copy()
    first_child = np.full(size, -1, dtype=np.int64)
    next_sibling = np.full(size, -1, dtype=np.int64)
    prev_sibling = np.full(size, -1, dtype=np.int64)
    _chains(parents, first_child, next_sibling, prev_sibling)
    stack = np.empty(size + 1, dtype=np.int64)
    _reduce(parents, conductances, is_segment, first_child, next_sibling,
            prev_sibling, alive, stack)
    return alive, parents, conductances


def reduce_tree(parents, conductances, segment_nodes):
    """Return (parents, conductances, segment_nodes) of the reduced tree.

    parents[k] is the parent of node k (-1 at a root), conductances[k] the edge
    conductance towards that parent, segment_nodes[i] the node carrying
    membrane segment i. Every segment and every branch point survives, so area,
    stimulus and recorded quantities are unchanged.
    """
    parents = np.ascontiguousarray(parents, dtype=np.int64)
    segments = np.ascontiguousarray(segment_nodes, dtype=np.int64)
    size = parents.shape[0]
    if size < 2 or segments.size == 0:
        conductances = np.ascontiguousarray(conductances, dtype=np.float64)
        return parents.copy(), conductances.copy(), segments.copy()
    alive, parents, conductances = reduce_structure(parents, conductances,
                                                    segment_nodes)
    is_segment = np.zeros(size, dtype=np.bool_)
    is_segment[segments] = True
    first_child = np.full(size, -1, dtype=np.int64)
    next_sibling = np.full(size, -1, dtype=np.int64)
    prev_sibling = np.full(size, -1, dtype=np.int64)
    _chains(parents, first_child, next_sibling, prev_sibling)
    order = np.empty(size, dtype=np.int64)
    roots = np.empty(size, dtype=np.int64)
    count, _ = _breadth_first(alive, parents, first_child, next_sibling, order,
                              roots)
    position = np.full(size, -1, dtype=np.int64)
    position[order[:count]] = np.arange(count, dtype=np.int64)
    nodes = order[:count]
    parent_of = parents[nodes]
    has_parent = parent_of >= 0
    new_parents = np.full(count, -1, dtype=np.int64)
    new_conductances = np.zeros(count, dtype=np.float64)
    new_parents[has_parent] = position[parent_of[has_parent]]
    new_conductances[has_parent] = conductances[nodes[has_parent]]
    new_segments = position[segments]
    if np.any(new_segments < 0):
        raise AssertionError("a membrane segment was removed by reduction")
    return new_parents, new_conductances, new_segments
