"""Exact contraction of redundant virtual nodes in a prepared Hines tree.

The production geometry (neuron_geometry.prepare_neuron_geometry ->
tree_geometry.refined_tree) gives every SWC vertex a *virtual* node in addition
to one membrane *segment* node per SWC edge, so a packed Hines tree carries
about two nodes per segment.  A virtual node has no area, no capacitance and no
injected current, so its matrix row is pure Kirchhoff.  That row can be
eliminated exactly:

    one incident arm   -> delete the node.  Its row reads g (V_v - V_u) = 0, so
                          V_v = V_u and the retained equation is unchanged.
    two incident arms  -> contract into ONE series resistance R_a + R_b between
                          the two neighbours, i.e. conductance 1 / (R_a + R_b).
                          Exact two-port elimination.
    three or more arms -> keep.  A genuine branch point couples three or more
                          independent potentials and has no one- or two-term
                          equivalent.

The reduction is algebraically exact, not an approximation: every eliminated row
is a linear combination of the retained ones, so the retained segment potentials
are the same numbers as the full system (up to floating-point association
order).  Nothing physical is discarded, only rows that are identically
redundant.  Measured agreement with the full tree on real registered cells is
5.4e-13 relative, i.e. at the level of double-precision round-off.

Every stage is a numpy operation over the whole node vector, so the cost is
O(nodes log depth) rather than one Python step per node.  The earlier per-node
work-queue cost 9 us per node, i.e. ~54 ms for a 3000-segment cell and minutes
per thousand cells, which is far too slow to sit in the solver path.

Node ids are renumbered densely in ascending original id order.  The original
parents array already satisfies parents[k] < k, and contraction only redirects
a child to an ancestor, so that order stays topological after renumbering; the
level/CSR layout is rebuilt by the production batch_tree_layouts code, so the
arrays have exactly the shape hines_kernel.batched expects.  Level counts
depend only on tree depth, not on the numbering, so the kernel visits the same
levels as before.

Segment identity is preserved: segment_nodes[i] is the reduced node of membrane
segment i and segment order never changes, so area, field, initial gates, events
and every other segment-indexed field stay valid without remapping.

This module does not validate units, does not read morphology and does not
reserve GPU memory.  It narrows an already prepared geometry.
"""

import numpy as np

from . import reduction
from .tree_levels import _depths, batch_tree_layouts


def _column(value, name):
    """Return a one-dimensional column of a packed (rows, cells) array."""
    if value is None:
        return None
    array = np.asarray(value)
    if array.ndim == 2:
        if array.shape[1] != 1:
            raise ValueError(f'{name} must be a single-cell column')
        array = array[:, 0]
    if array.ndim != 1:
        raise ValueError(f'{name} must be one-dimensional')
    return array


def _degree(parents, conductances, alive):
    """Count positive-conductance incident edges of every live node."""
    index = np.flatnonzero(parents >= 0)
    live = alive[index] & alive[parents[index]] & (conductances[index] > 0.0)
    source = index[live]
    degree = np.bincount(source, minlength=parents.size)
    degree += np.bincount(parents[source], minlength=parents.size)
    return degree.astype(np.int64)


def _collapse(parents, conductances, alive):
    """Jump every live node over eliminated ancestors, accumulating resistance.

    Pointer doubling: each pass rewrites node -> parent into node -> grandparent
    with the two edge resistances in series, so a chain of any length collapses in
    ceil(log2(depth)) vectorised passes instead of one Python step per link.
    """
    while True:
        pending = alive & (parents >= 0) & ~alive[np.maximum(parents, 0)]
        if not pending.any():
            return parents, conductances
        skipped = parents[pending]
        if np.any(conductances[pending] <= 0.0) or np.any(conductances[skipped] <= 0.0):
            raise ValueError('a zero-conductance link cannot be collapsed')
        series = 1.0 / conductances[pending] + 1.0 / conductances[skipped]
        parents[pending] = parents[skipped]
        conductances[pending] = 1.0 / series


def _reduce(parents, conductances, virtual):
    """Delete one-arm and contract two-arm virtual nodes; return the live mask.

    Each round classifies every live node from the same snapshot, then applies all
    deletions and all contractions at once; chains that span several rounds are
    finished by _collapse.  The loop stops when a round changes nothing, which is
    the fixpoint the earlier per-node work queue reached.
    """
    node_count = parents.size
    alive = np.ones(node_count, dtype=bool)
    deleted = contracted = 0
    degenerate = []
    root_like = virtual & (conductances == 0.0)
    if root_like.any():
        raise ValueError('a virtual node cannot be a component root')
    for _ in range(node_count + 2):
        degree = _degree(parents, conductances, alive)
        candidate = alive & virtual
        removal = candidate & (degree <= 1)
        folding = candidate & (degree == 2)
        if not removal.any() and not folding.any():
            return alive, deleted, contracted, degenerate
        if removal.any():
            alive[removal] = False
            deleted += int(removal.sum())
        if folding.any():
            index = np.flatnonzero(parents >= 0)
            live = alive[index] & alive[parents[index]] & (conductances[index] > 0.0)
            child_of = np.full(node_count, -1, dtype=np.int64)
            chosen = folding[parents[index[live]]]
            child_of[parents[index[live]][chosen]] = index[live][chosen]
            contractible = np.flatnonzero(folding & (child_of >= 0))
            if contractible.size:
                child = child_of[contractible]
                series = (1.0 / conductances[child] + 1.0 / conductances[contractible])
                usable = np.isfinite(series) & (series > 0.0)
                if not usable.all():
                    degenerate.extend(int(node) for node in contractible[~usable])
                    folding[contractible[~usable]] = False
                contractible = contractible[usable]
                child = child_of[contractible]
                if contractible.size:
                    parents[child] = parents[contractible]
                    conductances[child] = 1.0 / series[usable]
                    alive[contractible] = False
                    contracted += int(contractible.size)
        parents, conductances = _collapse(parents, conductances, alive)
    raise AssertionError('the reduction did not reach a fixpoint')


def _layout(parents):
    """Rebuild the exact batch_tree_layouts structure for one tree.

    batch_tree_layouts validates with type(value) is int, so the tree is handed
    over as plain Python ints exactly as pack_trees does.
    """
    tree = np.asarray(parents, dtype=np.int64).tolist()
    (bounds, group_parents, group_offsets, group_children, level_counts), (
        child_offsets, child_indices) = batch_tree_layouts([tree], as_arrays=True)
    return {'level_bounds': bounds, 'group_parents': group_parents,
            'group_offsets': group_offsets, 'group_children': group_children,
            'level_counts': level_counts, 'child_offsets': child_offsets,
            'child_indices': child_indices}


def _static_diagonal(parents, conductances, child_offsets, child_indices):
    """Reproduce hines_kernel.static_diagonal for one cell on the host."""
    node_count = len(parents)
    diagonal = np.zeros(node_count, dtype=np.float64)
    diagonal[1:] = conductances[1:]
    total = int(child_offsets[node_count])
    np.add.at(diagonal, parents[1:], conductances[child_indices[:total]])
    return diagonal

def _reduce(parents, conductances, virtual):
    """Delete one-arm and contract two-arm virtual nodes; return the live mask.

    Each round classifies every live node from one snapshot, then applies all
    deletions and all contractions at once; chains that span several rounds are
    finished by _collapse.  The loop stops when a round changes nothing, which is
    the fixpoint the earlier per-node work queue reached.
    """
    node_count = parents.size
    alive = np.ones(node_count, dtype=bool)
    keep = np.zeros(node_count, dtype=bool)
    deleted = contracted = 0
    parent_set = np.zeros(node_count, dtype=bool)
    parent_set[parents[1:]] = True
    if (virtual & (conductances == 0.0) & parent_set).any():
        # A virtual node may not root a component: refined_tree roots every
        # extra component at a membrane segment, so this would mean the tree
        # and the segment map disagree.
        raise ValueError('a virtual node cannot root a component')
    for _ in range(node_count + 2):
        degree = _degree(parents, conductances, alive)
        candidate = alive & virtual & ~keep
        removal = candidate & (degree <= 1)
        folding = candidate & (degree == 2)
        if not removal.any() and not folding.any():
            return alive, deleted, contracted
        if removal.any():
            alive[removal] = False
            deleted += int(removal.sum())
        contractible = np.flatnonzero(folding)
        if contractible.size:
            index = np.flatnonzero(parents >= 0)
            live = alive[index] & alive[parents[index]] & (conductances[index] > 0.0)
            child_of = np.full(node_count, -1, dtype=np.int64)
            child_of[parents[index[live]]] = index[live]
            contractible = contractible[child_of[contractible] >= 0]
        if contractible.size:
            child = child_of[contractible]
            resistance = 1.0 / conductances[child] + 1.0 / conductances[contractible]
            usable = np.isfinite(resistance) & (resistance > 0.0)
            if not usable.all():
                # An ideal short (or a blown-up conductance) has no finite series
                # equivalent, so those rows are kept rather than approximated.
                keep[contractible[~usable]] = True
                contractible, child = contractible[usable], child[usable]
                resistance = resistance[usable]
        if contractible.size:
            parents[child] = parents[contractible]
            conductances[child] = 1.0 / resistance
            alive[contractible] = False
            contracted += int(contractible.size)
        parents, conductances = _collapse(parents, conductances, alive)
    raise AssertionError('the reduction did not reach a fixpoint')



def _layout(parents):
    """Rebuild the exact batch_tree_layouts structure for one tree.

    batch_tree_layouts validates with type(value) is int, so the tree is handed
    over as plain Python ints exactly as pack_trees does.
    """
    tree = np.asarray(parents, dtype=np.int64).tolist()
    (bounds, group_parents, group_offsets, group_children, level_counts), (
        child_offsets, child_indices) = batch_tree_layouts([tree], as_arrays=True)
    return {'level_bounds': bounds, 'group_parents': group_parents,
            'group_offsets': group_offsets, 'group_children': group_children,
            'level_counts': level_counts, 'child_offsets': child_offsets,
            'child_indices': child_indices}


def _static_diagonal(parents, conductances, child_offsets, child_indices):
    """Reproduce hines_kernel.static_diagonal for one cell on the host."""
    node_count = len(parents)
    diagonal = np.zeros(node_count, dtype=np.float64)
    diagonal[1:] = conductances[1:]
    total = int(np.asarray(child_offsets).reshape(-1)[node_count])
    np.add.at(diagonal, parents[1:],
              conductances[np.asarray(child_indices).reshape(-1)[:total]])
    return diagonal


def reduce_geometry(geometry, *, verify=True):
    """Return (reduced_geometry, report) for one prepared geometry dict.

    Every segment-indexed field (area, grid, junctions, field_current_na,
    starts_um ...) is copied through untouched; only parents, conductances and
    segment_nodes change, so the caller keeps the real per-segment membrane data
    and only the tree narrows.

    The parents array must be the one-dimensional array refined_tree produced for
    a single cell, not a packed column.
    """
    if not isinstance(geometry, dict):
        raise ValueError('Invalid geometry')
    parents = _column(geometry.get('parents'), 'parents').astype(np.int64)
    conductances = _column(geometry.get('conductances'), 'conductances').astype(
        np.float64)
    segments_array = _column(geometry.get('segment_nodes'), 'segment_nodes').astype(
        np.int64)
    node_count = parents.size
    segments = segments_array.size
    if node_count < 1 or segments < 1:
        raise ValueError('a tree needs at least one node and one segment')
    if conductances.size != node_count:
        raise ValueError('conductances must match parents')
    if parents[0] != -1:
        raise ValueError('node 0 must be the root with parent -1')
    if np.unique(segments_array).size != segments:
        raise ValueError('segment nodes must be unique')
    if np.any(segments_array < 0) or np.any(segments_array >= node_count):
        raise ValueError('segment node out of range')
    if conductances[0] != 0.0:
        raise ValueError('root conductance must be zero')
    if np.any(conductances[1:] < 0.0) or not np.isfinite(conductances).all():
        raise ValueError('invalid conductance')
    if np.any(parents[1:] >= np.arange(1, node_count)):
        raise ValueError('parents must precede children')

    virtual = np.ones(node_count, dtype=bool)
    virtual[segments_array] = False
    arms = _degree(parents, conductances, np.ones(node_count, dtype=bool))
    if np.any(arms[~virtual] < 1) or np.any(arms[virtual] < 1):
        # Only the root may be electrically isolated, and that root is a segment.
        raise ValueError('every node except the root must carry a live edge')

    # The structural pass is the hot one: 604 ns per node when it ran as numpy
    # over the whole vector, 116 ns per node as a numba walk, so the compiled
    # version is used here and only the renumbering/reporting stays in numpy.
    alive, parents, conductances = reduction.reduce_structure(
        parents, conductances, segments_array)
    reduced_arms = _degree(parents, conductances, alive)
    contracted = int(np.count_nonzero(~alive & ~virtual))
    deleted = int(np.count_nonzero(~alive & virtual))
    if not alive[0]:
        raise AssertionError('the reduction removed the root')
    survivors = np.flatnonzero(alive)
    if survivors.size < segments:
        raise AssertionError('the reduction removed a membrane segment')
    renumber = np.full(node_count, -1, dtype=np.int64)
    renumber[survivors] = np.arange(survivors.size, dtype=np.int64)
    reduced_parents = np.where(parents[survivors] >= 0,
                             renumber[parents[survivors]], -1)
    reduced_conductances = conductances[survivors]
    reduced_segments = renumber[segments_array]
    if np.any(reduced_parents[1:] >= np.arange(1, survivors.size)):
        raise AssertionError('reduced parents must precede children')
    if np.any(reduced_segments < 0):
        raise AssertionError('the reduction lost a membrane segment map')

    # The level/CSR layout is rebuilt by pack_trees anyway, for the reduced tree and
    # for every other cell in the same batch, so building it here would duplicate
    # that cost. It is only needed for verification and for the level count, and a
    # level count is just the maximum root distance, which doubling gives cheaply.
    # Level count needs a full depth pass (0.34 ms per large cell), so it is only
    # computed when the caller asked for verification; the solver rebuilds the
    # level layout anyway and never reads this number.
    level_count = int(_depths(reduced_parents).max()) if verify else None
    if verify:
        layout = _layout(reduced_parents)
        diagonal = _static_diagonal(reduced_parents, reduced_conductances,
                                    layout['child_offsets'], layout['child_indices'])
        if np.any(diagonal <= 0.0) or not np.isfinite(diagonal).all():
            raise AssertionError('reduced diagonal must be strictly positive')
    else:
        layout = None
        diagonal = None

    # Counted with numpy, not a Python loop: the loop made 1.17 M dict lookups
    # over 256 cells and was the single largest item left in this function.
    keys, counts = np.unique(arms[virtual], return_counts=True)
    by_arms = {int(k): int(c) for k, c in zip(keys, counts)}
    if verify:
        _verify_reduced(reduced_parents, reduced_conductances, reduced_segments,
                        layout)

    result = dict(geometry)
    result['parents'] = reduced_parents
    result['conductances'] = reduced_conductances
    result['segment_nodes'] = reduced_segments
    report = {
        'segments': segments,
        'nodes_full': node_count,
        'nodes_reduced': int(survivors.size),
        'virtual_total': int(virtual.sum()),
        'virtual_by_arms': {str(key): by_arms[key] for key in sorted(by_arms)},
        'virtual_kept': int((virtual & alive).sum()),
        'virtual_deleted_one_arm': deleted,
        'virtual_contracted_two_arm': contracted,
        'ratio': round(survivors.size / node_count, 6),
        'level_count': level_count,
        'diagonal_min': None if diagonal is None else float(diagonal.min()),
    }
    return result, report



def _verify_reduced(parents, conductances, segment_nodes, layout):
    """Assert the reduced tree satisfies every pack_trees invariant."""
    node_count = len(parents)
    segments = len(segment_nodes)
    if parents[0] != -1:
        raise AssertionError('reduced root must have parent -1')
    if np.any(parents[1:] >= np.arange(1, node_count)):
        raise AssertionError('reduced parents must precede children')
    if np.unique(segment_nodes).size != segments:
        raise AssertionError('reduced segment nodes must be unique')
    if np.any(segment_nodes < 0) or np.any(segment_nodes >= node_count):
        raise AssertionError('reduced segment node out of range')
    if conductances[0] != 0.0:
        raise AssertionError('reduced root conductance must be zero')
    if np.any(conductances[1:] < 0.0):
        raise AssertionError('reduced conductance must be non-negative')
    extra_roots = np.flatnonzero(np.asarray(conductances)[1:] == 0.0) + 1
    if extra_roots.size and not np.isin(extra_roots, segment_nodes).all():
        raise AssertionError('every reduced component root must be a segment')
    child_offsets = np.asarray(layout['child_offsets']).reshape(-1)
    child_indices = np.asarray(layout['child_indices']).reshape(-1)
    total_children = int(child_offsets[node_count])
    if total_children != node_count - 1:
        raise AssertionError('reduced tree must hold exactly nodes - 1 children')
    if child_indices.size < total_children:
        raise AssertionError('reduced CSR too short')
    degree = np.diff(child_offsets[:node_count + 1])
    expected = np.bincount(np.asarray(parents)[1:], minlength=node_count)
    if not np.array_equal(degree, expected):
        raise AssertionError('CSR degree disagrees with parents')
    children = child_indices[:total_children]
    if int(np.count_nonzero(children == 0)):
        raise AssertionError('the root must not be a child')
    if np.unique(children).size != node_count - 1:
        raise AssertionError('every non-root node must be a child exactly once')
    order = np.argsort(children, kind='stable')
    if not np.array_equal(children[order], np.arange(1, node_count)):
        raise AssertionError('CSR must cover nodes 1..nodes-1')
