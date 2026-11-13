"""Validated geometry packing for experimental heterogeneous Hines batches."""

from dataclasses import dataclass

import numpy as np

from .tree_levels import batch_tree_layouts


@dataclass(frozen=True)
class PackedTrees:
    parents: np.ndarray
    conductances: np.ndarray
    segment_nodes: np.ndarray
    node_segments: np.ndarray
    lengths: np.ndarray
    nodes: np.ndarray
    level_bounds: np.ndarray
    group_parents: np.ndarray
    group_offsets: np.ndarray
    group_children: np.ndarray
    child_offsets: np.ndarray
    child_indices: np.ndarray
    level_counts: np.ndarray


def pack_trees(trees, *, reuse=None, layouts=None):
    """Pack ``(parents, conductances, segment_nodes)`` in caller order.

    Reject duplicate segment nodes, negative conductances and non-tree
    parent layouts before they can reach a CUDA kernel. This function does not
    reserve GPU memory or validate the physical model or units.
    """
    if not isinstance(trees, (list, tuple)) or not trees:
        raise ValueError('At least one tree is required')
    validated = []
    for item in trees:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise ValueError('Invalid tree')
        parents, conductances, segments = (np.asarray(value) for value in item)
        if (parents.ndim != 1 or not np.issubdtype(parents.dtype, np.integer)
                or conductances.shape != parents.shape
                or not np.issubdtype(conductances.dtype, np.number)
                or np.iscomplexobj(conductances) or segments.ndim != 1
                or not np.issubdtype(segments.dtype, np.integer)
                or len(segments) == 0 or len(parents) == 0
                or not np.isfinite(conductances).all() or conductances[0] != 0
                or np.any(conductances[1:] < 0)
                or np.any(segments < 0) or np.any(segments >= len(parents))):
            raise ValueError('Invalid tree arrays')
        # Duplicate and membership tests use one O(n) mark array instead of
        # np.unique/np.isin sorts. The sort version dominated batch packing:
        # 7.3 s for a 1,019-cell batch, i.e. more than the whole solve budget
        # for the population, and the mark array answers the identical question.
        marks = np.zeros(len(parents), dtype=bool)
        marks[segments] = True
        if int(np.count_nonzero(marks)) != len(segments):
            raise ValueError('Invalid tree arrays')
        component_roots = np.flatnonzero(conductances[1:] == 0) + 1
        if len(component_roots) and (not marks[0]
                                     or not bool(marks[component_roots].all())):
            raise ValueError('Disconnected component root must be a membrane segment')
        validated.append((parents.astype(np.int64), conductances.astype(np.float64),
                          segments.astype(np.int64)))

    batch = len(validated)
    node_count = max(len(item[0]) for item in validated)
    segment_count = max(len(item[2]) for item in validated)
    # Pass the dense arrays straight through. Converting every column to a
    # Python list first made a 501-cell batch cost 71 s of host time.
    (bounds, group_parents, group_offsets, group_children, level_counts), (
        child_offsets, child_indices) = batch_tree_layouts(
            [item[0] for item in validated], as_arrays=True, layouts=layouts)

    def _column(dtype, rows, extra=0):
        """Return a zeroed (rows, batch) column, reusing scratch when allowed.

        Allocating and zeroing these columns afresh cost ~1.5 GB of first-touch
        page faults per batch, which measured 0.27 us per padded node - ten
        times too slow to pack a whole population. With reuse=True the arrays
        come from a persistent pool that is only zeroed over the used window.
        """
        key = (np.dtype(dtype).str, rows)
        pool = None
        if reuse is not None:
            entry = reuse.get(key)
            if entry is not None and entry.shape[0] >= rows and entry.shape[1] >= batch:
                pool = entry
            else:
                grown = np.zeros((max(rows, 1), max(batch, 1)), dtype=dtype)
                reuse[key] = grown
                pool = grown
        if pool is not None:
            column = pool[:rows, :batch]
            if extra:
                column[:] = extra
            else:
                column[:] = 0
            return column
        column = np.zeros((rows, batch), dtype=dtype)
        if extra:
            column[:] = extra
        return column

    def _fill(column, arrays):
        """Fill a dense (rows, batch) column from per-cell 1-D arrays."""
        for cell, array in enumerate(arrays):
            column[:array.size, cell] = array
        return column

    parents = _fill(_column(np.int64, node_count), [p for p, _, _ in validated])
    conductances = _fill(_column(np.float64, node_count),
                         [g for _, g, _ in validated])
    segment_nodes = _fill(_column(np.int64, segment_count),
                          [s for _, _, s in validated])
    node_segments = _column(np.int64, node_count, extra=-1)
    lengths = np.zeros(batch, dtype=np.int64)
    nodes = np.zeros(batch, dtype=np.int64)
    for cell, (p, _, segment) in enumerate(validated):
        node_segments[segment, cell] = np.arange(segment.size, dtype=np.int64)
        lengths[cell] = segment.size
        nodes[cell] = p.size
    return PackedTrees(parents, conductances, segment_nodes, node_segments, lengths, nodes,
                       *(np.asarray(item, dtype=np.int64) for item in
                         (bounds, group_parents, group_offsets, group_children,
                          child_offsets, child_indices, level_counts)))
