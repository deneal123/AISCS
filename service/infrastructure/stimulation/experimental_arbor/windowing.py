"""Bounded sample harvesting for the unpublished Arbor experiment.

The callback must durably handle every sample and spike before it returns.
The simulator's sampling buffers and spike recorder are cleared only after
the callback succeeds. This helper does not validate solver equivalence.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from numbers import Real
from typing import Any

import numpy as np


@dataclass(frozen=True)
class SampleWindow:
    start_ms: float
    end_ms: float
    samples: dict[str, list[tuple[np.ndarray, Any]]]
    spikes: np.ndarray


def run_windowed(simulation, handles: dict[str, Any], *, duration_ms: float, dt_ms: float,
                 window_ms: float, ms_unit, on_window: Callable[[SampleWindow], None]) -> None:
    """Run fixed-step windows, handing off data before clearing recorders.

    The simulation must be at time zero, and every handle must have been
    attached before this call.  The caller owns setup, spike recording,
    persistent storage, cancellation and the semantics of the observed data.
    """
    values = (duration_ms, dt_ms, window_ms)
    if (any(isinstance(value, bool | np.bool_) or not isinstance(value, Real)
            or not math.isfinite(value) or value <= 0 for value in values)
            or not isinstance(handles, dict) or not handles
            or any(not isinstance(key, str) or not key for key in handles)
            or not callable(on_window)):
        raise ValueError('Invalid windowed simulation parameters')
    total_steps = round(duration_ms / dt_ms)
    window_steps = round(window_ms / dt_ms)
    if (total_steps < 1 or window_steps < 1
            or not math.isclose(total_steps * dt_ms, duration_ms, rel_tol=0, abs_tol=1e-9)
            or not math.isclose(window_steps * dt_ms, window_ms, rel_tol=0, abs_tol=1e-9)):
        raise ValueError('Windows and duration must align to the integration step')
    previous_times: dict[tuple[str, int], float] = {}
    for first in range(0, total_steps, window_steps):
        last = min(first + window_steps, total_steps)
        start, end = first * dt_ms, last * dt_ms
        simulation.run(end * ms_unit, dt_ms * ms_unit)
        captured = {}
        for key, handle in handles.items():
            entries = []
            for index, (values, metadata) in enumerate(simulation.samples(handle)):
                try:
                    array = np.asarray(values, dtype=np.float64).copy()
                except (TypeError, ValueError) as exc:
                    raise ValueError('Invalid sample values') from exc
                if (array.ndim != 2 or array.shape[1] < 2 or not np.isfinite(array).all()
                        or (len(array) and (np.any(np.diff(array[:, 0]) <= 0)
                            or array[0, 0] < start - 1e-9 or array[-1, 0] >= end + 1e-9
                            or array[0, 0] <= previous_times.get((key, index), -math.inf)))):
                    raise ValueError('Invalid, repeated or out-of-window sample times')
                if len(array):
                    previous_times[(key, index)] = float(array[-1, 0])
                entries.append((array, metadata))
            captured[key] = entries
        spikes = np.asarray(simulation.spikes()).copy()
        if (spikes.ndim != 1 or spikes.dtype.names is None or 'time' not in spikes.dtype.names
                or not np.isfinite(spikes['time']).all()
                or np.any(spikes['time'] < start - 1e-9)
                or np.any(spikes['time'] >= end + 1e-9)):
            raise ValueError('Invalid spike buffer')
        on_window(SampleWindow(start, end, captured, spikes))
        # Arbor clears BOTH sample and spike buffers here. Never clear before
        # the callback has accepted and persisted the current window.
        simulation.clear_samplers()
