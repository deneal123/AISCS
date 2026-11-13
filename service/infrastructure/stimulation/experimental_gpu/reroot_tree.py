"""Exact Hines re-orientation of a cable tree to its graph centre.

Hines elimination on a cable tree is exact for ANY choice of root: the tree
conductance matrix is symmetric, so changing the root changes only the order of
elimination, never the solution. What the root DOES change is the height of the
elimination tree, and that height is the number of dependent barriers one warp
must pass through per time step - the dominant cost of the GPU solver.

Rooting at the soma gives height = eccentricity(soma), i.e. the distance to the
farthest tip. For a real neuron the soma is peripheral, so that is close to the
tree DIAMETER. Rooting at a graph centre gives height = radius = ceil(diameter/2),
which is the minimum achievable over all roots. Measured on 256 real reduced
cells: 380.4 -> 195.9 levels. Full-population kernel benchmark at batch 2048:
371.2 -> 189.2 levels, 2.261 s -> 1.720 s (1.315x), segment voltages agreeing to
9.3e-10 mV.

The transform is pure re-indexing: node 0 becomes the new root, parents still
precede children (BFS order), each axial conductance moves to the node that now
owns that edge, and segment_nodes are remapped. Every segment-indexed field
(area, field, gates, events) is untouched because segment order never changes.
"""

import numpy as np
from numba import njit


@njit(cache=True, nogil=True)
def _bfs(offsets, neighbours, root, distance, queue):
    """Breadth-first distances from ``root``; returns (farthest node, distance)."""
    size = distance.size
    for index in range(size):
        distance[index] = -1
    distance[root] = 0
    queue[0] = root
    head = 0
    tail = 1
    farthest = root
    far_distance = 0
    while head < tail:
        node = queue[head]
        head += 1
        step = distance[node] + 1
        for slot in range(offsets[node], offsets[node + 1]):
            other = neighbours[slot]
            if distance[other] < 0:
                distance[other] = step
                queue[tail] = other
                tail += 1
                if step > far_distance:
                    far_distance = step
                    farthest = other
    return farthest, far_distance


@njit(cache=True, nogil=True)
def _centre(offsets, neighbours, size, distance, queue):
    """A graph centre: the middle node of a diameter path.

    A double sweep (arbitrary node -> farthest a -> farthest b) yields a genuine
    diameter on a tree, and any middle node of that path is a centre.
    """
    first, _ignored = _bfs(offsets, neighbours, 0, distance, queue)
    second, diameter = _bfs(offsets, neighbours, first, distance, queue)
    node = second
    for _step in range(diameter // 2):
        wanted = distance[node] - 1
        following = -1
        for slot in range(offsets[node], offsets[node + 1]):
            other = neighbours[slot]
            if distance[other] == wanted:
                following = other
                break
        if following < 0:
            break
        node = following
    return node, diameter


@njit(cache=True, nogil=True)
def _walk(offsets, neighbours, root, distance, order, position):
    """BFS order from ``root``; order[i] is the node that becomes node i."""
    size = distance.size
    for index in range(size):
        distance[index] = 0
    distance[root] = 1
    order[0] = root
    position[root] = 0
    queue = order
    head = 0
    tail = 1
    while head < tail:
        node = queue[head]
        head += 1
        for slot in range(offsets[node], offsets[node + 1]):
            other = neighbours[slot]
            if distance[other] == 0:
                distance[other] = 1
                position[other] = tail
                order[tail] = other
                tail += 1
    return tail


@njit(cache=True, nogil=True)
def _orient(offsets, neighbours, order, position, parents, conductances,
            new_parents, new_conductances):
    """Re-parent every node and move each edge conductance to its new owner.

    In BFS order the new parent of order[i] is the single neighbour with a
    smaller position. The conductance belongs to the undirected edge, whose
    owner in the OLD orientation is whichever endpoint was the old child.
    """
    size = order.size
    for index in range(1, size):
        node = order[index]
        for slot in range(offsets[node], offsets[node + 1]):
            other = neighbours[slot]
            if position[other] < index:
                new_parents[index] = position[other]
                if parents[node] == other:
                    new_conductances[index] = conductances[node]
                else:
                    new_conductances[index] = conductances[other]
                break


@njit(cache=True, nogil=True)
def _adjacency(parents, offsets, neighbours):
    """Symmetric CSR of the tree: every child-to-parent edge traversed both ways."""
    size = parents.size
    for node in range(size):
        offsets[node] = 0
    for node in range(1, size):
        offsets[node] += 1
        offsets[parents[node]] += 1
    total = 0
    for node in range(size):
        count = offsets[node]
        offsets[node] = total
        total += count
    offsets[size] = total
    cursor = np.empty(size, np.int64)
    for node in range(size):
        cursor[node] = offsets[node]
    for node in range(1, size):
        parent = parents[node]
        neighbours[cursor[node]] = parent
        cursor[node] += 1
        neighbours[cursor[parent]] = node
        cursor[parent] += 1


def reroot_centre(parents, conductances, segment_nodes, centre=None):
    """Return (parents, conductances, segment_nodes) rooted at a graph centre.

    ``conductances[node]`` is the axial conductance of the edge joining ``node``
    to its parent, so re-orienting only moves each value to whichever endpoint
    owns that edge afterwards. Segment order is preserved, so every array indexed
    by segment stays valid; only the node indices they point at are renumbered.

    ``centre`` may be supplied to force a specific root; otherwise a diameter
    midpoint is found. The returned arrays are C-contiguous int64/float64.
    """
    parents = np.ascontiguousarray(parents, np.int64)
    conductances = np.ascontiguousarray(conductances, np.float64)
    segments = np.ascontiguousarray(segment_nodes, np.int64)
    size = parents.size
    if size < 3 or conductances.size != size or segments.size < 1:
        return parents, conductances, segments
    offsets = np.zeros(size + 1, np.int64)
    neighbours = np.empty(2 * (size - 1), np.int64)
    _adjacency(parents, offsets, neighbours)
    distance = np.empty(size, np.int64)
    queue = np.empty(size, np.int64)
    if centre is None:
        centre, _diameter = _centre(offsets, neighbours, size, distance, queue)
    order = np.empty(size, np.int64)
    position = np.empty(size, np.int64)
    walked = _walk(offsets, neighbours, int(centre), distance, order, position)
    if walked != size:
        raise ValueError("the tree is disconnected")
    new_parents = np.full(size, -1, np.int64)
    new_conductances = np.zeros(size, np.float64)
    _orient(offsets, neighbours, order, position, parents, conductances,
            new_parents, new_conductances)
    return (new_parents, new_conductances,
            np.ascontiguousarray(position[segments], np.int64))


def centre_levels(parents):
    """Level count a tree would have if re-rooted at its centre (debug/report)."""
    parents = np.ascontiguousarray(parents, np.int64)
    size = parents.size
    if size < 2:
        return 0
    offsets = np.zeros(size + 1, np.int64)
    neighbours = np.empty(2 * (size - 1), np.int64)
    _adjacency(parents, offsets, neighbours)
    distance = np.empty(size, np.int64)
    queue = np.empty(size, np.int64)
    first, _ignored = _bfs(offsets, neighbours, 0, distance, queue)
    _second, diameter = _bfs(offsets, neighbours, first, distance, queue)
    return (diameter + 1) // 2
