"""Build a Hines tree from discretized cable resistances for GPU experiments."""

import math
from collections import deque

import numpy as np


def refined_tree(edges, parent_resistance, child_resistance, segment_counts, *, allow_forest=False):
    """Return parents, conductances and segment-node indices in BFS order.

    An edge is ``(child_id, parent_id)``. Resistances are ordered by the
    input edges and segments, respectively. No geometry or units are inferred.
    """
    if not edges or len(edges) != len(child_resistance):
        raise ValueError('Invalid cable edges or child resistances')
    children = [edge[0] for edge in edges]
    if len(set(children)) != len(children):
        raise ValueError('Repeated child edge')
    if any(type(segment_counts.get(child)) is not int or segment_counts[child] < 1
           for child in children):
        raise ValueError('Invalid segment count')
    segment_total = sum(segment_counts[child] for child in children)
    if len(parent_resistance) != segment_total:
        raise ValueError('Incorrect number of segment resistances')
    # Segments and SWC vertices occupy disjoint integer ID spaces. This
    # preserves graph insertion/BFS order while avoiding tuple allocation for
    # every adjacency entry in large reconstructions.
    vertices = {}
    for child, parent in edges:
        if parent not in vertices:
            vertices[parent] = segment_total + len(vertices)
        if child not in vertices:
            vertices[child] = segment_total + len(vertices)
    adjacency = {}

    def link(a, b, resistance):
        if not math.isfinite(resistance) or resistance <= 0:
            raise ValueError('Invalid cable resistance')
        conductance = 1.0 / resistance
        adjacency.setdefault(a, []).append((b, conductance))
        adjacency.setdefault(b, []).append((a, conductance))

    offset = 0
    for (child, parent), end_resistance in zip(edges, child_resistance, strict=True):
        previous = vertices[parent]
        count = segment_counts[child]
        for segment in range(count):
            current = offset + segment
            link(previous, current, parent_resistance[offset + segment])
            previous = current
        offset += count
        link(previous, vertices[child], end_resistance)
    order = [0]
    parents = [-1]
    conductances = [0.0]
    seen = set(order)
    queue = deque([0])
    next_component = 0
    while queue or len(seen) < len(adjacency):
        if not queue:
            if not allow_forest:
                raise ValueError('Disconnected cable graph')
            while next_component < offset and next_component in seen:
                next_component += 1
            if next_component == offset:
                raise ValueError('Disconnected component has no segment')
            node = next_component
            seen.add(node)
            order.append(node)
            parents.append(0)
            conductances.append(0.0)
            queue.append(len(order) - 1)
        current = queue.popleft()
        for node, conductance in adjacency[order[current]]:
            if node not in seen:
                seen.add(node)
                order.append(node)
                parents.append(current)
                conductances.append(conductance)
                queue.append(len(order) - 1)
            elif parents[current] < 0 or node != order[parents[current]]:
                raise ValueError('Cable graph contains a cycle')
    if len(order) != len(adjacency):
        raise ValueError('Disconnected cable graph')
    indices = {node: index for index, node in enumerate(order)}
    return (np.asarray(parents, dtype=np.int64), np.asarray(conductances),
            np.asarray([indices[i] for i in range(offset)], dtype=np.int64))
