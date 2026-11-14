"""Validate a physical cell's per-edge discretization for feedback replay."""


def grid_configuration(grid, edge_ids):
    """Return a verified configuration for a complete, contiguous segment grid."""
    if not isinstance(grid, (list, tuple)) or len(grid) != len(edge_ids) or not grid:
        raise ValueError('Invalid population event grid')
    counts = {}
    current = None
    next_index = 0
    for item, edge in zip(grid, edge_ids, strict=True):
        if (not isinstance(item, (list, tuple)) or len(item) != 3
                or any(type(value) is not int for value in item)):
            raise ValueError('Invalid population event grid')
        child, segment, count = item
        if child != int(edge) or child <= 0 or count < 1 or count % 2 != 1:
            raise ValueError('Invalid population event grid')
        if child != current:
            if current is not None and next_index != counts[current]:
                raise ValueError('Incomplete population event grid')
            if child in counts:
                raise ValueError('Noncontiguous population event grid')
            counts[child] = count
            current, next_index = child, 0
        if count != counts[child] or segment != next_index:
            raise ValueError('Invalid population event grid')
        next_index += 1
    if next_index != counts[current]:
        raise ValueError('Incomplete population event grid')
    return {'nseg_per_edge': 1,
            'nseg_by_edge': {str(child): count for child, count in counts.items() if count != 1}}
