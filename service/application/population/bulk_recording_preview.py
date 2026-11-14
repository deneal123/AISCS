"""Bounded visual preview of an independent detailed-population recording."""

import numpy as np


def bulk_recording_preview(recording, *, max_bins=400):
    """Retain actual per-bin extrema; never invent network events or stimulus."""
    if (not isinstance(recording, dict) or type(recording.get('cells')) is not int
            or recording['cells'] < 1 or type(max_bins) is not int or not 1 <= max_bins <= 1000
            or not isinstance(recording.get('interpretation'), str)
            or 'no network feedback' not in recording['interpretation']
            or not isinstance(recording.get('replacement_receipts'), list)):
        raise ValueError('Invalid independent recording preview')
    time = np.asarray(recording.get('time_ms'), dtype=float)
    signal = np.asarray(recording.get('neural_uv'), dtype=float)
    if (time.ndim != 1 or len(time) < 2 or signal.shape != time.shape
            or not np.isfinite(time).all() or not np.isfinite(signal).all()
            or time[0] != 0 or np.any(np.diff(time) <= 0)):
        raise ValueError('Invalid independent recording samples')
    edges = np.linspace(0, len(time), min(max_bins, len(time)) + 1, dtype=int)
    indices = set()
    for start, end in zip(edges[:-1], edges[1:], strict=True):
        indices.update((int(start), int(end - 1), int(start + np.argmin(signal[start:end])),
                        int(start + np.argmax(signal[start:end]))))
    indices = np.array(sorted(indices), dtype=int)
    return {'kind': 'experimental-independent-population', 'cells': recording['cells'],
            'samples': len(time), 'shown_samples': len(indices),
            'time_ms': time[indices].tolist(), 'neural_uv': signal[indices].tolist(),
            'units': {'time_ms': 'ms', 'neural_uv': 'µV'},
            'replacement_count': len(recording['replacement_receipts']),
            'interpretation': recording['interpretation']}
