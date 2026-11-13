"""Adapt an experimental GPU cell result to existing recording consumers."""

import numpy as np


def as_reference_arrays(geometry, cell, time_ms):
    """Validate arrays and return the shape used by existing recording code.

    This adapter does not create provenance or assert that a result came from
    a particular morphology. A caller must independently bind geometry,
    result and simulation configuration before publishing or replaying it.
    """
    if not isinstance(geometry, dict) or not isinstance(cell, dict):
        raise ValueError('Invalid GPU result')
    keys = ('starts_um', 'ends_um', 'midpoints_um', 'endpoint_radii_um',
            'diameters_um', 'edge_node_ids')
    try:
        arrays = {key: np.asarray(geometry[key], dtype=None if key == 'edge_node_ids' else float)
                  for key in keys}
        time = np.asarray(time_ms, dtype=float)
        voltage = np.asarray(cell['voltage_mv'], dtype=float)
        current = np.asarray(cell['membrane_current_na'], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Invalid GPU result arrays') from exc
    count = len(arrays['edge_node_ids']) if arrays['edge_node_ids'].ndim == 1 else 0
    if (count == 0 or arrays['edge_node_ids'].dtype.kind not in 'iu'
            or np.any(arrays['edge_node_ids'] <= 0)
            or any(arrays[key].shape != (count, 3) for key in
                   ('starts_um', 'ends_um', 'midpoints_um'))
            or arrays['endpoint_radii_um'].shape != (count, 2)
            or arrays['diameters_um'].shape != (count,)
            or time.ndim != 1 or len(time) < 2 or np.any(np.diff(time) <= 0)
            or voltage.shape != (count, len(time)) or current.shape != voltage.shape
            or any(not np.isfinite(array).all() for array in
                   (*arrays.values(), time, voltage, current))
            or np.any(arrays['endpoint_radii_um'] <= 0)
            or np.any(arrays['diameters_um'] <= 0)
            or not np.allclose(arrays['midpoints_um'],
                               (arrays['starts_um'] + arrays['ends_um']) / 2,
                               rtol=1e-12, atol=1e-12)):
        raise ValueError('Incompatible GPU result arrays')
    return {**arrays, 'time_ms': time, 'voltage_mv': voltage, 'membrane_current_na': current}
