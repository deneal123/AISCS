"""Source-space landmarks from MaleCNS SWC; never estimates missing somata.

An unlocated neuron is represented by an actual reconstructed neurite vertex
nearest its cable-length centroid. This is a drawing landmark, not an electrical
source or an inferred cell body. The source EM frame remains in micrometres.
"""

from __future__ import annotations

import math


def _validated_nodes(text: str, *, include_radii: bool = False) -> dict:
    nodes = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 7:
            raise ValueError("Malformed SWC row")
        index, kind, parent = int(fields[0]), int(fields[1]), int(fields[6])
        xyz = tuple(float(v) * 0.008 for v in fields[2:5])
        radius = float(fields[5]) * 0.008
        if (
            index <= 0
            or index in nodes
            or parent == index
            or not all(math.isfinite(v) for v in (*xyz, radius))
            or radius < 0
        ):
            raise ValueError("Invalid SWC vertex")
        nodes[index] = (xyz, parent, kind, radius) if include_radii else (xyz, parent, kind)
    if not nodes:
        raise ValueError("Empty SWC")
    roots = 0
    visited = set()
    for index, node in nodes.items():
        parent = node[1]
        if parent == -1:
            roots += 1
        elif parent not in nodes:
            raise ValueError("Unresolved SWC parent")
        path = set()
        current = index
        while current != -1 and current not in visited:
            if current in path:
                raise ValueError("Cyclic SWC")
            path.add(current)
            current = nodes[current][1] if current in nodes else -1
        visited.update(path)
    if not roots:
        raise ValueError("SWC has no root")
    return nodes


def validate_swc_topology(text: str) -> None:
    """Check syntax, geometry and topology without calculating display landmarks."""
    _validated_nodes(text)


def neurite_landmark(text: str) -> dict:
    nodes = _validated_nodes(text)
    total, sums, roots = 0.0, [0.0, 0.0, 0.0], 0
    for xyz, parent, _ in nodes.values():
        if parent == -1:
            roots += 1
        else:
            other = nodes[parent][0]
            length = math.dist(xyz, other)
            total += length
            for axis in range(3):
                sums[axis] += length * (xyz[axis] + other[axis]) / 2
    centroid = (
        tuple(value / total for value in sums)
        if total
        else tuple(sum(v[0][axis] for v in nodes.values()) / len(nodes) for axis in range(3))
    )
    selected = min(nodes, key=lambda i: (math.dist(nodes[i][0], centroid), i))
    return {
        "anchor_um": list(nodes[selected][0]),
        "swc_vertex": selected,
        "vertices": len(nodes),
        "components": roots,
        "cable_length_um": total,
        "bounds_um": [
            [min(v[0][j] for v in nodes.values()), max(v[0][j] for v in nodes.values())]
            for j in range(3)
        ],
        "method": "nearest-swc-vertex-to-cable-centroid-v1",
    }
