"""Compare two numerical recordings without declaring either one correct."""

from __future__ import annotations

import numpy as np


def compare_recordings(coarse_time_ms, coarse_uv, reference_time_ms, reference_uv):
    """Compare coincident samples; the reference must contain the coarse grid.

    This reports observed differences, not an accuracy bound or physiological
    validation. In particular, a finer time step is not ground truth.
    """
    coarse_t = np.asarray(coarse_time_ms, dtype=float)
    coarse_y = np.asarray(coarse_uv, dtype=float)
    reference_t = np.asarray(reference_time_ms, dtype=float)
    reference_y = np.asarray(reference_uv, dtype=float)
    if (coarse_t.ndim != 1 or reference_t.ndim != 1 or len(coarse_t) < 2
            or len(reference_t) < len(coarse_t) or coarse_y.shape != coarse_t.shape
            or reference_y.shape != reference_t.shape
            or not all(np.isfinite(value).all() for value in
                       (coarse_t, coarse_y, reference_t, reference_y))
            or np.any(np.diff(coarse_t) <= 0) or np.any(np.diff(reference_t) <= 0)
            or abs(coarse_t[0] - reference_t[0]) > 1e-9
            or abs(coarse_t[-1] - reference_t[-1]) > 1e-9):
        raise ValueError('Incompatible recording grids')
    indices = np.searchsorted(reference_t, coarse_t)
    indices = np.minimum(indices, len(reference_t) - 1)
    # A floating point timestamp can fall slightly to the right of its exact
    # match. Check both neighbours and choose the nearest without interpolation.
    left = np.maximum(indices - 1, 0)
    indices = np.where(abs(reference_t[left] - coarse_t) < abs(reference_t[indices] - coarse_t),
                       left, indices)
    if np.any(np.abs(reference_t[indices] - coarse_t) > 1e-9):
        raise ValueError('Reference does not contain the recording grid')
    try:
        with np.errstate(over='raise', invalid='raise'):
            difference = coarse_y - reference_y[indices]
            peak = float(np.max(np.abs(reference_y[indices])))
            maximum = float(np.max(np.abs(difference)))
            rms = float(np.sqrt(np.mean(difference * difference)))
            relative = maximum / peak if peak else None
    except (FloatingPointError, OverflowError) as exc:
        raise ValueError('Recording difference is not finite') from exc
    if relative is not None and not np.isfinite(relative):
        raise ValueError('Recording difference is not finite')
    return {'samples': len(coarse_t), 'max_abs_difference_uv': maximum,
            'rms_difference_uv': rms,
            'reference_peak_uv': peak,
            'max_difference_over_reference_peak': relative,
            'interpretation': 'samplewise numerical difference; not an accuracy bound'}


def compare_edge_events(events, reference_events):
    """Compare integer graph event counts at each directed pair and tick."""
    def index(rows):
        if not isinstance(rows, list):
            raise ValueError('Invalid graph event list')
        result = {}
        for row in rows:
            if (not isinstance(row, dict)
                    or any(type(row.get(key)) is not int or row[key] <= 0
                           for key in ('source_id', 'target_id', 'tick', 'count'))):
                raise ValueError('Invalid graph event')
            key = row['source_id'], row['target_id'], row['tick']
            if key in result:
                raise ValueError('Duplicate graph event')
            result[key] = row['count']
        return result

    actual, reference = index(events), index(reference_events)
    keys = set(actual) | set(reference)
    return {'changed_source_partner_ticks': sum(actual.get(key, 0) != reference.get(key, 0)
                                                 for key in keys),
            'absolute_count_difference': sum(abs(actual.get(key, 0) - reference.get(key, 0))
                                             for key in keys),
            'interpretation': 'difference in model graph events; not measured spikes'}
