"""Conservative boxes for reconstructed SWC edges, not inferred anatomy."""

from __future__ import annotations

import math

import numpy as np


def segment_boxes(swc: str, *, bin_um: float = 16, max_edges: int = 32) -> np.ndarray:
    """Group edges by midpoint bin, bounding both ends of each edge.

    Isolated roots are represented as zero-length segments. The returned boxes
    conservatively contain all input segments; they are only an initial filter.
    """
    if (not math.isfinite(bin_um) or bin_um <= 0 or type(max_edges) is not int
            or max_edges <= 0):
        raise ValueError("Invalid segmentation settings")
    nodes = {}
    for line in swc.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 7:
            raise ValueError("Malformed SWC")
        node, parent = int(fields[0]), int(fields[6])
        point = np.asarray([float(value) * .008 for value in fields[2:5]])
        if node <= 0 or node in nodes or not np.isfinite(point).all() or parent == node:
            raise ValueError("Invalid SWC vertex")
        nodes[node] = (point, parent)
    if not nodes:
        raise ValueError("Empty SWC")
    parents = {parent for _, parent in nodes.values() if parent != -1}
    edges = []
    for node, (point, parent) in nodes.items():
        if parent == -1:
            if node not in parents:
                edges.append((point, point))
        elif parent not in nodes:
            raise ValueError("Missing SWC parent")
        else:
            edges.append((nodes[parent][0], point))
    if not edges:
        raise ValueError("No SWC segments")
    values = np.asarray(edges)
    bins_float = np.floor(values.mean(axis=1) / bin_um)
    if not np.isfinite(bins_float).all() or np.any(np.abs(bins_float) >= 2**62):
        raise ValueError("SWC exceeds numerical range")
    bins = bins_float.astype(np.int64)
    order = np.lexsort((bins[:, 2], bins[:, 1], bins[:, 0]))
    values, bins = values[order], bins[order]
    breaks = np.flatnonzero(np.any(bins[1:] != bins[:-1], axis=1)) + 1
    boxes = []
    for section in np.split(values, breaks):
        for start in range(0, len(section), max_edges):
            points = section[start:start + max_edges].reshape(-1, 3)
            boxes.append(np.concatenate((points.min(axis=0), points.max(axis=0))))
    return np.asarray(boxes)


def boxes_match(boxes: np.ndarray, contacts, radius_um: float) -> bool:
    """Whether either contact's query cube intersects at least one box."""
    boxes = np.asarray(boxes, dtype=float)
    contacts = np.asarray(contacts, dtype=float)
    if (boxes.ndim != 2 or boxes.shape[1] != 6 or not len(boxes)
            or contacts.shape != (2, 3) or not np.isfinite(boxes).all()
            or not np.isfinite(contacts).all() or not math.isfinite(radius_um)
            or radius_um < 0 or np.any(boxes[:, :3] > boxes[:, 3:])):
        raise ValueError("Invalid boxes or query")
    return any(np.any(np.all(boxes[:, :3] <= point + radius_um, axis=1)
                      & np.all(boxes[:, 3:] >= point - radius_um, axis=1))
               for point in contacts)
