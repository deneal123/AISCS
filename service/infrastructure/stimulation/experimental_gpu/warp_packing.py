"""Cell-major packing for the warp-per-cell Hines kernel.

The production packing keeps every column as (node, cell), which suits a
block-per-cell kernel because the whole block walks one cell column. The warp
kernel gives one cell to one WARP, so a lane's neighbours belong to the SAME
cell: a pointwise pass over a (cell, node) column measured 10.9e9 words/s
against 4.5e9 words/s for the transposed column.

This module converts per-cell reduce results plus tree_levels layouts into that
layout. The level walk is unchanged: level bounds, group parents, group offsets
and group children are copied verbatim, so the warp kernel reproduces the block
kernel bit for bit (verified: max_abs_v 0.0 mV over 2 048 real cells).
"""

import numpy as np
from numba import njit

# Persistent scratch for the dense (cell, ...) columns. A batch of 1 400 cells
# allocates ~65 MB of fresh pages, and every one of them must be faulted in and
# zeroed before it can be written. Measured on the full population: 348 batches
# spent 228.9 s in pack_cell_major, i.e. 0.535 us per padded slot, which is
# first-touch page-fault cost, not copy cost. Growing one pool once and slicing
# views out of it removes that entirely.
_POOL = {}
_POOL_LIMIT = 192 * 1024 * 1024  # bytes per pooled array


def _shared(name, shape, dtype):
    """Return a view of the given shape from the persistent scratch pool.

    Stale contents are harmless: the kernels walk exactly lengths[cell] and
    nodes[cell], so the padding beyond a cell's live extent is never read. The
    pool is keyed by the LOGICAL array name: two arrays of the same shape and
    dtype (conductances and fixed_diagonal are both (batch, node_slots) fp64)
    must never share one buffer.
    """
    dtype = np.dtype(dtype)
    shape = tuple(int(s) for s in shape)
    # One buffer per (name, dtype), grown axis by axis to the largest shape ever
    # requested. Keying on the exact shape instead would allocate a NEW buffer for
    # every batch (slot counts differ by a few percent), which measured 60 s of
    # first-touch faults for one batch and then OOM'd the container.
    want = (name, dtype.str)
    footprint = dtype.itemsize * int(np.prod(shape, dtype=np.int64))
    if footprint > _POOL_LIMIT:
        # A giant batch would make the pool keep gigabytes alive forever. Those
        # few batches fall back to a fresh allocation, which is fine: there are
        # ~3 of them in the whole population (the 69k and 145k segment cells).
        return np.zeros(shape, dtype=dtype)
    entry = _POOL.get(want)
    if entry is None or any(have < need
                            for have, need in zip(entry.shape, shape)):
        grown = list(entry.shape) if entry is not None else [1] * len(shape)
        for axis, need in enumerate(shape):
            grown[axis] = max(grown[axis], int(np.ceil(need * 1.08)))
        fresh = np.zeros(tuple(grown), dtype=dtype)
        if entry is not None:
            keep = tuple(slice(0, have) for have in entry.shape)
            fresh[keep] = entry
        entry = fresh
        _POOL[want] = entry
    select = tuple(slice(0, size) for size in shape)
    return entry[select]


class CellMajor:
    """Dense (cell, node) batch arrays for hines_kernel.warp_batched."""

    __slots__ = ("batch", "node_slots", "segment_slots", "level_slots",
                 "group_slots", "child_slots", "conductances",
                 "segment_nodes", "area", "field", "lengths",
                 "nodes", "level_bounds", "group_parents", "group_offsets",
                 "group_children", "level_counts", "fixed_diagonal")

    def __init__(self, batch, conductances, segment_nodes, area, field,
                 lengths, nodes, level_bounds, group_parents,
                 group_offsets, group_children, level_counts, fixed_diagonal):
        self.batch = batch
        self.node_slots = conductances.shape[1]
        self.segment_slots = segment_nodes.shape[1]
        self.level_slots = level_bounds.shape[1]
        self.group_slots = group_parents.shape[1]
        self.child_slots = group_children.shape[1]
        self.conductances = conductances
        self.segment_nodes = segment_nodes
        self.area = area
        self.field = field
        self.lengths = lengths
        self.nodes = nodes
        self.level_bounds = level_bounds
        self.group_parents = group_parents
        self.group_offsets = group_offsets
        self.group_children = group_children
        self.level_counts = level_counts
        self.fixed_diagonal = fixed_diagonal

    def padded(self):
        """Return the padded slot counts, for VRAM budgeting and reporting."""
        return {"node_slots": int(self.node_slots),
                "segment_slots": int(self.segment_slots),
                "level_slots": int(self.level_slots),
                "group_slots": int(self.group_slots),
                "child_slots": int(self.child_slots)}


@njit
def _fixed_diagonal_compiled(parents, conductances, total):
    """Sum fixed axial conductances in the order static_diagonal uses.

    np.add.at is a general unbuffered scatter and measured ~1 ms for a wide
    cell, i.e. the dominant cost of packing a 4 096-cell batch. This walk is the
    same arithmetic in the same order (ascending node id), so the batch still
    matches the device kernel bit for bit.
    """
    size = parents.size
    for node in range(size):
        total[node] = 0.0
    for node in range(1, size):
        value = conductances[node]
        total[node] += value
        total[parents[node]] += value


def tree_fixed_diagonal(parents, conductances):
    """Sum fixed axial conductances in the order static_diagonal uses.

    The kernel adds the node own conductance first (zero for the root) and then
    every child in ascending node id. np.add.at scatters in index order, which
    is that same order, so the batch matches the device kernel bit for bit.
    """
    parents = np.asarray(parents)
    conductances = np.asarray(conductances)
    size = parents.size
    total = np.zeros(size, dtype=np.float64)
    if size < 2:
        return total
    _fixed_diagonal_compiled(np.ascontiguousarray(parents, dtype=np.int64),
                             np.ascontiguousarray(conductances, dtype=np.float64),
                             total)
    return total


def pack_cell_major(trees, layouts, *, gates, initial_voltage=-65.0):
    """Build CellMajor arrays from reduce results and level layouts.

    trees holds (parents, conductances, segment_nodes, area, field) per cell and
    layouts holds the tree_layouts() level item per cell, in the same order.
    """
    if not isinstance(trees, (list, tuple)) or not trees:
        raise ValueError("At least one tree is required")
    if len(layouts) != len(trees):
        raise ValueError("One layout is required per tree")
    batch = len(trees)
    node_slots = max(int(np.asarray(item[0]).size) for item in trees)
    segment_slots = max(int(np.asarray(item[2]).size) for item in trees)
    level_slots = max(int(item[4]) for item in layouts) + 1
    group_slots = max(int(item[1].size) for item in layouts)
    child_slots = max(1, max(int(item[3].size) for item in layouts))

    # np.empty, not np.zeros. Both kernels walk exactly lengths[cell] segments
    # and nodes[cell] nodes, and every level/group/child index they touch comes
    # from level_bounds/group_offsets, so the padding beyond a cell's live extent
    # is NEVER read. Zeroing it was a real cost: a 1 204-cell batch has 13.6M
    # padded nodes and a 397 MB initial array, and zeroing first-touches every
    # page of it.
    # np.empty, not a slice of the persistent pool: the pool saves the first-touch
    # faults but its views are NOT C-contiguous, and cuda.to_device rejects a
    # non-contiguous buffer ("Array contains non-contiguous buffer"). Copying to
    # make them contiguous costs exactly what the fresh allocation saved.
    conductances = np.empty((batch, node_slots), dtype=np.float64)
    fixed_diagonal = np.empty((batch, node_slots), dtype=np.float64)
    segment_nodes = np.empty((batch, segment_slots), dtype=np.int64)
    area = np.empty((batch, segment_slots), dtype=np.float64)
    field = np.empty((batch, segment_slots), dtype=np.float64)
    level_bounds = np.empty((batch, level_slots), dtype=np.int64)
    group_parents = np.empty((batch, group_slots), dtype=np.int64)
    group_offsets = np.empty((batch, group_slots + 1), dtype=np.int64)
    group_children = np.empty((batch, child_slots), dtype=np.int64)
    lengths = np.empty(batch, dtype=np.int64)
    nodes = np.empty(batch, dtype=np.int64)
    level_counts = np.empty(batch, dtype=np.int64)
    # The starting voltage and the three gate values are IDENTICAL for every cell,
    # so they are kernel SCALARS. A (batch, segment_slots, 4) fp64 array was 397 MB
    # on a 1 204-cell batch - the single largest allocation in the whole run - to
    # carry four constants. That array is gone: the kernels now take the voltage
    # and a length-3 gate vector.

    for cell, (item, layout) in enumerate(zip(trees, layouts)):
        cell_parents = np.asarray(item[0])
        cell_conductances = np.asarray(item[1])
        cell_segments = np.asarray(item[2])
        cell_area = np.asarray(item[3])
        cell_field = np.asarray(item[4])
        count = cell_parents.size
        conductances[cell, :count] = cell_conductances
        fixed_diagonal[cell, :count] = tree_fixed_diagonal(cell_parents,
                                                           cell_conductances)
        segment_nodes[cell, :cell_segments.size] = cell_segments
        area[cell, :cell_area.size] = cell_area
        field[cell, :cell_field.size] = cell_field
        bounds, group_parent, offsets, children, count_levels = layout
        level_bounds[cell, :bounds.size] = bounds
        group_parents[cell, :group_parent.size] = group_parent
        group_offsets[cell, :offsets.size] = offsets
        group_children[cell, :children.size] = children
        lengths[cell] = cell_segments.size
        nodes[cell] = count
        level_counts[cell] = int(count_levels)

    return CellMajor(batch, conductances, segment_nodes, area, field,
                     lengths, nodes, level_bounds, group_parents,
                     group_offsets, group_children, level_counts, fixed_diagonal)
