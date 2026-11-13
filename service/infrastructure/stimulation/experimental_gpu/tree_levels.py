"""Race-free work layout for a rooted, topologically ordered Hines tree.

This module only plans work. A GPU implementation must still synchronize
between levels and reduce each parent's children before writing that parent.

Every routine has a numpy path: the per-node Python version cost 3.5 ms for a
5 900-node tree and 12.4 ms for a 23 800-node tree, and the layout is rebuilt
for every cell, so at 166 700 cells the Python cost alone would exceed the
whole end-to-end budget. The arrays below are computed with one vectorised
pass over the node vector and produce byte-identical layouts.
"""

import numpy as np
from numba import njit


@njit(cache=True, nogil=True)
def _depths_compiled(array, depth):
    """Root distance of every node in ONE pass (parents precede children)."""
    size = array.shape[0]
    depth[0] = 0
    for node in range(1, size):
        depth[node] = depth[array[node]] + 1


def _depths(array):
    """Root distance of every node as a fresh array (topological order input).

    Kept as a public-ish helper because reduced_tree.py needs a level count for
    its verification pass even when it deliberately skips the level layout.
    """
    array = np.ascontiguousarray(array, dtype=np.int64)
    depth = np.empty(array.size, dtype=np.int64)
    if array.size:
        _depths_compiled(array, depth)
    return depth


@njit(cache=True, nogil=True)
def _bucket_by_level(array, depth, level_start, order, level_count):
    """Counting sort of the children by level, ascending child id inside a level."""
    for level in range(level_count):
        level_start[level] = 0
    size = array.shape[0]
    for child in range(1, size):
        level_start[depth[child] - 1] += 1
    total = 0
    for level in range(level_count):
        count = level_start[level]
        level_start[level] = total
        total += count
    level_start[level_count] = total
    cursor = level_start.copy()
    for child in range(1, size):
        level = depth[child] - 1
        order[cursor[level]] = child
        cursor[level] += 1


@njit(cache=True, nogil=True)
def _group_levels(array, level_start, order, stamp, parent_group, group_parent,
                  child_group, bounds, level_count):
    """Assign every child to a group, groups ordered by their first child id.

    A parent's children all share one level, but they need not be adjacent in
    ascending-child-id order inside that level: a sibling of another parent can
    sit between them. The group a parent already owns must therefore be looked
    up, not assumed to be the most recently created one, or a later sibling is
    attached to a foreign parent and the elimination silently solves a
    different matrix.
    """
    size = array.shape[0]
    for node in range(size):
        stamp[node] = -1
    groups = 0
    bounds[0] = 0
    for level in range(level_count):
        start = level_start[level]
        stop = level_start[level + 1]
        for position in range(start, stop):
            child = order[position]
            parent = array[child]
            if stamp[parent] != level:
                stamp[parent] = level
                parent_group[parent] = groups
                group_parent[groups] = parent
                groups += 1
            child_group[child] = parent_group[parent]
        bounds[level + 1] = groups
    return groups


@njit(cache=True, nogil=True)
def _children_by_group(child_group, offsets, cursor, children, groups):
    """Scatter children grouped by group id, ascending child id inside a group."""
    size = child_group.shape[0]
    for group in range(groups):
        cursor[group] = 0
    for child in range(1, size):
        cursor[child_group[child]] += 1
    total = 0
    for group in range(groups):
        offsets[group] = total
        count = cursor[group]
        cursor[group] = total
        total += count
    offsets[groups] = total
    for child in range(1, size):
        group = child_group[child]
        children[cursor[group]] = child
        cursor[group] += 1


def _depth_and_levels(array):
    """Return (depth, level_start, order, level_count) for a validated tree."""
    size = array.size
    depth = np.empty(size, dtype=np.int64)
    _depths_compiled(array, depth)
    level_count = int(depth.max()) if size > 1 else 0
    if level_count <= 0:
        return depth, np.zeros(1, np.int64), np.zeros(max(size - 1, 0), np.int64), 0  # noqa: E501
    level_start = np.zeros(level_count + 1, dtype=np.int64)
    order = np.empty(size - 1, dtype=np.int64)
    _bucket_by_level(array, depth, level_start, order, level_count)
    return depth, level_start, order, level_count


def _level_groups(array):
    """Return the level-grouped layout of one tree as flat arrays.

    O(nodes) in compiled code. The numpy version this replaces ran one stable
    sort, one unique and one lexsort per tree and measured 20 s per 746-cell
    batch, which is more than the GPU solve of that batch; the layout is only
    needed to order the Hines level walk, so an exact O(nodes) build is used.
    Group order inside a level follows the smallest child id that reaches the
    parent, and children inside a group keep ascending node id, which is the
    order the original per-node implementation produced.
    """
    node_count = array.size
    empty = (np.zeros(1, np.int64), np.zeros(0, np.int64), np.zeros(1, np.int64),
             np.zeros(0, np.int64), 0)
    if node_count < 2:
        return empty
    depth, level_start, order, level_count = _depth_and_levels(array)
    stamp = np.full(node_count, -1, dtype=np.int64)
    parent_group = np.empty(node_count, dtype=np.int64)
    group_parent = np.empty(node_count, dtype=np.int64)
    child_group = np.empty(node_count, dtype=np.int64)
    bounds = np.zeros(level_count + 2, dtype=np.int64)
    groups = _group_levels(array, level_start, order, stamp, parent_group,
                           group_parent, child_group, bounds, level_count)
    offsets = np.zeros(groups + 1, dtype=np.int64)
    cursor = np.empty(groups + 1, dtype=np.int64)
    children = np.empty(max(node_count - 1, 1), dtype=np.int64)
    _children_by_group(child_group, offsets, cursor, children, groups)
    return (bounds[:level_count + 1], group_parent[:groups], offsets,
            children[:node_count - 1], level_count)


def _parent_array(parents):
    """Validate a rooted tree and return it as a dense int64 parent array.

    The checks are the same ones the per-node version made: node 0 is the root,
    every parent is a plain integer that precedes its child. A non-integer or
    out-of-range entry is rejected rather than coerced.
    """
    if isinstance(parents, np.ndarray):
        # Fast path: the batch packer already holds dense int64 arrays. Going
        # through list() here cost 7.4M Python object conversions for a 501-cell
        # batch (71 s of host time) and produced the identical layout.
        if parents.ndim != 1 or parents.size == 0:
            raise ValueError('Invalid rooted tree')
        array = np.array(parents, dtype=np.int64, copy=True)
    else:
        if not isinstance(parents, (list, tuple)) or not parents:
            raise ValueError('Invalid rooted tree')
        array = np.asarray(parents)
    if array.ndim != 1 or array.dtype.kind not in 'iu':
        raise ValueError('Invalid rooted tree')
    array = array.astype(np.int64, copy=True)
    if array[0] != -1:
        raise ValueError('Invalid rooted tree')
    node_count = array.size
    if node_count > 1:
        child = array[1:]
        if np.any(child < 0) or np.any(child >= np.arange(1, node_count, dtype=np.int64)):
            raise ValueError('Parents must precede children')
    return array


def parent_groups_by_level(parents):
    """Return root-to-leaf levels of ``(parent, children)`` groups.

    Root index 0 must have parent -1; every other parent must precede its
    child. In a level each parent occurs once, so assigning one worker to a
    complete group avoids simultaneous writes from siblings.
    """
    array = _parent_array(parents)
    bounds, groups, offsets, children, level_count = _level_groups(array)
    levels = []
    for level in range(level_count):
        start, stop = int(bounds[level]), int(bounds[level + 1])
        levels.append([(int(groups[group]),
                        tuple(int(node) for node in
                              children[int(offsets[group]):int(offsets[group + 1])]))
                       for group in range(start, stop)])
    return levels



def children_csr(parents):
    """Return offsets and children for the same validated rooted tree.

    Each node owns its consecutive children, allowing independent GPU workers
    to sum incident conductances and currents without atomic writes.
    """
    array = _parent_array(parents)
    offsets, children = _children_from_parents(array)
    return offsets.tolist(), children.tolist()


@njit(cache=True, nogil=True)
def _children_from_parents_compiled(array, offsets, cursor, children):
    """Order children by parent in one pass, ascending id inside a parent.

    The offsets must already hold the cumulative child counts. Visiting the
    children in ascending node id scatters them into ascending order inside
    each parent, which is exactly what a stable argsort by parent returns;
    that sort cost O(nodes log nodes) per tree and this pass is O(nodes).
    """
    size = array.shape[0]
    for node in range(size):
        cursor[node] = offsets[node]
    for child in range(1, size):
        parent = array[child]
        children[cursor[parent]] = child
        cursor[parent] += 1


def _children_from_parents(array):
    """Return the child CSR of one tree from its parent array alone.

    Children of one parent keep ascending node id, because the level walk
    visited the nodes in ascending order.
    """
    node_count = array.size
    offsets = np.zeros(node_count + 1, dtype=np.int64)
    if node_count < 2:
        return offsets, np.zeros(0, dtype=np.int64)
    np.cumsum(np.bincount(array[1:], minlength=node_count), out=offsets[1:])
    children = np.empty(node_count - 1, dtype=np.int64)
    cursor = np.empty(node_count, dtype=np.int64)
    _children_from_parents_compiled(array, offsets, cursor, children)
    return offsets, children


def batch_children_csr(trees):
    """Pack independent CSR trees into node-major, zero-padded lists.

    Offsets in each column refer only to that column's child indices. Tree
    lengths must accompany these arrays when a kernel traverses the batch.
    """
    if not isinstance(trees, (list, tuple)) or not trees:
        raise ValueError('At least one tree is required')
    packed = [_children_from_parents(_parent_array(tree)) for tree in trees]
    return _pack_children_csr(packed)


def _pack_children_csr(packed, *, as_arrays=False):
    max_offsets = max(len(offsets) for offsets, _ in packed)
    # Preserve rank two when every tree consists only of the root. GPU
    # kernels still compile their (unreached) two-dimensional indexing.
    max_children = max(1, *(len(indices) for _, indices in packed))
    if as_arrays:
        offsets = np.zeros((max_offsets, len(packed)), dtype=np.int64)
        indices = np.zeros((max_children, len(packed)), dtype=np.int64)
        for cell, (cell_offsets, cell_indices) in enumerate(packed):
            offsets[:cell_offsets.size, cell] = cell_offsets
            indices[:cell_indices.size, cell] = cell_indices
        return offsets, indices
    offsets = [[0] * len(packed) for _ in range(max_offsets)]
    indices = [[0] * len(packed) for _ in range(max_children)]
    for cell, (cell_offsets, cell_indices) in enumerate(packed):
        for row, value in enumerate(cell_offsets.tolist()):
            offsets[row][cell] = value
        for row, value in enumerate(cell_indices.tolist()):
            indices[row][cell] = value
    return offsets, indices



def batch_parent_groups(trees):
    """Pack independent level-grouped trees, with per-cell level counts.

    Every offset and parent/child index is local to its cell's column. Zero
    padding must not be traversed beyond the returned level count.
    """
    if not isinstance(trees, (list, tuple)) or not trees:
        raise ValueError('At least one tree is required')
    return _pack_parent_levels([_level_groups(_parent_array(tree)) for tree in trees])


def _pack_parent_levels(all_levels, *, as_arrays=False):
    packed = [(bounds, groups, offsets, children)
              for bounds, groups, offsets, children, _ in all_levels]
    columns = []
    for field in range(4):
        rows = max(1, *(len(item[field]) for item in packed))
        if as_arrays:
            column = np.zeros((rows, len(all_levels)), dtype=np.int64)
            for cell, item in enumerate(packed):
                column[:item[field].size, cell] = item[field]
            columns.append(column)
            continue
        column = [[0] * len(all_levels) for _ in range(rows)]
        for cell, item in enumerate(packed):
            for row, value in enumerate(item[field].tolist()):
                column[row][cell] = value
        columns.append(column)
    return (*columns, [item[0].size - 1 for item in packed])


def tree_layouts(array):
    """Return both race-free layouts of ONE already validated parent array.

    Splitting the per-tree part out of batch_tree_layouts lets a caller build
    the layouts on worker threads while the batch is still being collected: the
    level/CSR construction is three sorts per tree (3.2 s for a 2 000-cell
    batch) while the final column assembly is only 0.05 s, so this is the part
    that has to be parallel.
    """
    item = _level_groups(array)
    return item, _children_from_parents(array)


def batch_tree_layouts(trees, *, as_arrays=False, layouts=None):
    """Validate and pack both layouts while computing tree levels once."""
    if not isinstance(trees, (list, tuple)) or not trees:
        raise ValueError('At least one tree is required')
    arrays = [_parent_array(tree) for tree in trees]
    if layouts is None:
        layouts = [tree_layouts(array) for array in arrays]
    elif len(layouts) != len(arrays):
        raise ValueError('One layout is required per tree')
    levels = [item[0] for item in layouts]
    parent_layout = _pack_parent_levels(levels, as_arrays=as_arrays)
    if as_arrays:
        # Parent validation and topological ordering were checked above, and the
        # parent-array CSR is a stable sort by child id, which is exactly the
        # order the ascending level walk produced.
        child_layout = _pack_children_csr([item[1] for item in layouts],
                                          as_arrays=True)
    else:
        child_layout = _pack_children_csr([
            _children_csr_from_levels(node_count, item)
            for node_count, item in zip((array.size for array in arrays), levels,
                                        strict=True)])
    return parent_layout, child_layout


def _children_csr_from_levels(node_count, item):
    """Rebuild the child CSR from a level layout for the list-returning API."""
    _, groups, offsets, children, _ = item
    lists = [[] for _ in range(node_count)]
    for group in range(groups.size):
        start, stop = int(offsets[group]), int(offsets[group + 1])
        lists[int(groups[group])].extend(int(node)
                                         for node in children[start:stop])
    total = [0]
    for group in lists:
        total.append(total[-1] + len(group))
    return (np.asarray(total, dtype=np.int64),
            np.asarray([node for group in lists for node in group], dtype=np.int64))
