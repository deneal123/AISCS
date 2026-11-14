"""Bounded accumulation of experimental population electrode recordings."""

import numpy as np

from .window_recording import WindowedPointRecorder


class PopulationRecording:
    """Accumulate independent currents and optionally stream selected voltages.

    Selected-window sinks receive provisional data: callers must stage it and
    publish only after the entire solver and ``finish`` have both succeeded.
    This helper does not establish network coupling.
    """

    def __init__(self, expected_ids, *, electrode_um, reference_um, conductivity_s_m,
                 clearance_um, samples, selection_factory=None, selected_sink=None):
        if (not isinstance(expected_ids, (list, tuple)) or not expected_ids
                or any(type(body) is not int or body <= 0 for body in expected_ids)
                or len(set(expected_ids)) != len(expected_ids)
                or type(samples) is not int or samples < 2
                or (selection_factory is None) != (selected_sink is None)
                or (selection_factory is not None and not callable(selection_factory))
                or (selected_sink is not None and not callable(selected_sink))):
            raise ValueError('Invalid population recording identities or samples')
        self.expected = set(expected_ids)
        self.completed = set()
        self.signal = np.zeros(samples, dtype=float)
        self.electrode = electrode_um
        self.reference = reference_um
        self.conductivity = conductivity_s_m
        self.clearance = clearance_um
        self.samples = samples
        self.active = False
        self.failed = False
        self.selection_factory = selection_factory
        self.selected_sink = selected_sink

    def factory(self, cells):
        if self.failed or self.active or not isinstance(cells, list) or not cells:
            raise ValueError('Invalid population recording batch state')
        ids = [cell.get('id') if isinstance(cell, dict) else None for cell in cells]
        if (any(type(body) is not int for body in ids) or len(set(ids)) != len(ids)
                or any(body not in self.expected or body in self.completed for body in ids)):
            raise ValueError('Invalid population recording batch identities')
        recorder = WindowedPointRecorder({cell['id']: cell['geometry'] for cell in cells},
            self.electrode, self.reference, self.conductivity, clearance_um=self.clearance,
            samples=self.samples)
        selection = ({body: [] for body in ids} if self.selection_factory is None
                     else self.selection_factory(cells))
        if (not isinstance(selection, dict) or list(selection) != ids
                or any(not isinstance(selection[body], list)
                       or any(type(index) is not int or not 0 <= index <
                              len(recorder.coefficients[body]) for index in selection[body])
                       or len(set(selection[body])) != len(selection[body]) for body in ids)):
            raise ValueError('Invalid population segment selection')
        self.active = True
        position = 0

        def accept(start, end, rows):
            nonlocal position
            try:
                if (not self.active or type(start) is not int or type(end) is not int
                        or start != position or not start < end <= self.samples
                        or not isinstance(rows, list)
                        or [row.get('id') if isinstance(row, dict) else None
                            for row in rows] != ids):
                    raise ValueError('Invalid population recording window')
                values = np.zeros(end - start, dtype=float)
                for row in rows:
                    trace = np.asarray(row.get('neural_uv'), dtype=float)
                    if trace.shape != values.shape or not np.isfinite(trace).all():
                        raise ValueError('Invalid population recording values')
                    if self.selected_sink is not None:
                        selected = np.asarray(row.get('selected_voltage_mv'), dtype=float)
                        if (selected.shape != (len(selection[row['id']]), end - start)
                                or not np.isfinite(selected).all()):
                            raise ValueError('Invalid population selected voltage')
                    values += trace
                combined = self.signal[start:end] + values
                if not np.isfinite(combined).all():
                    raise ValueError('Non-finite population recording')
                if self.selected_sink is not None:
                    self.selected_sink(start, end, rows, selection)
                self.signal[start:end] = combined
                position = end
                if position == self.samples:
                    self.completed.update(ids)
                    self.active = False
            except Exception:
                self.failed = True
                raise

        return {'recording_coefficients': recorder.coefficients,
                'selected_indices': selection, 'sink': accept}

    def finish(self):
        if self.failed or self.active or self.completed != self.expected:
            raise ValueError('Incomplete population recording')
        return self.signal.copy()
