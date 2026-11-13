"""Retain only explicitly selected segment traces from ordered GPU windows."""

import numpy as np


class WindowedTraceSelector:
    """Store selected traces for subsequent checks using existing event semantics.

    The caller must independently establish how segment indices map to
    verified candidate synapses. This class neither infers that mapping nor
    interprets voltage crossings as biological spikes.
    """

    def __init__(self, segment_counts, selected_indices, *, samples):
        if (not isinstance(segment_counts, dict) or not segment_counts
                or not isinstance(selected_indices, dict)
                or list(segment_counts) != list(selected_indices)
                or type(samples) is not int or samples < 2):
            raise ValueError('Invalid selected trace configuration')
        self.ids = list(segment_counts)
        self.counts = dict(segment_counts)
        self.indices = {}
        self.traces = {}
        self.samples = samples
        self.next_sample = 0
        for body in self.ids:
            count, indexes = segment_counts[body], selected_indices[body]
            if (type(body) is not int or body <= 0 or type(count) is not int or count < 1
                    or not isinstance(indexes, list)
                    or any(type(index) is not int or not 0 <= index < count for index in indexes)
                    or len(set(indexes)) != len(indexes)):
                raise ValueError('Invalid selected segment indexes')
            self.indices[body] = np.asarray(indexes, dtype=np.int64)
            self.traces[body] = np.empty((len(indexes), samples), dtype=np.float64)

    def accept(self, start, end, rows):
        if (type(start) is not int or type(end) is not int or start != self.next_sample
                or not start < end <= self.samples or not isinstance(rows, list)
                or [row.get('id') if isinstance(row, dict) else None for row in rows] != self.ids):
            raise ValueError('Invalid or out-of-order trace window')
        selected = {}
        for row in rows:
            body = row['id']
            voltage = np.asarray(row.get('voltage_mv'), dtype=np.float64)
            if voltage.shape != (self.counts[body], end - start):
                raise ValueError('Invalid window voltage shape')
            values = voltage[self.indices[body]]
            if not np.isfinite(values).all():
                raise ValueError('Non-finite selected voltage')
            selected[body] = values
        for body, values in selected.items():
            self.traces[body][:, start:end] = values
        self.next_sample = end

    def finish(self):
        if self.next_sample != self.samples:
            raise ValueError('Incomplete selected traces')
        return {body: values.copy() for body, values in self.traces.items()}

    def accept_selected(self, start, end, rows):
        """Accept values already gathered in the configured segment order."""
        if (type(start) is not int or type(end) is not int or start != self.next_sample
                or not start < end <= self.samples or not isinstance(rows, list)
                or [row.get('id') if isinstance(row, dict) else None for row in rows] != self.ids):
            raise ValueError('Invalid or out-of-order trace window')
        selected = {}
        for row in rows:
            body = row['id']
            values = np.asarray(row.get('selected_voltage_mv'), dtype=np.float64)
            if (values.shape != (len(self.indices[body]), end - start)
                    or not np.isfinite(values).all()):
                raise ValueError('Invalid selected voltage window')
            selected[body] = values
        for body, values in selected.items():
            self.traces[body][:, start:end] = values
        self.next_sample = end
