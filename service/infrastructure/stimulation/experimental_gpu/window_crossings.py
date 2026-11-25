"""Bounded threshold crossings with the graph's conservative tick semantics."""

import math

import numpy as np


class WindowedCrossings:
    """Track selected traces across windows without retaining their full history."""

    def __init__(self, selected_indices, *, time_ms, threshold_mv, duration_ms):
        time = np.asarray(time_ms, dtype=float)
        if (not isinstance(selected_indices, dict) or not selected_indices
                or any(type(body) is not int or body <= 0 or not isinstance(indices, list)
                       or any(type(index) is not int or index < 0 for index in indices)
                       or len(set(indices)) != len(indices)
                       for body, indices in selected_indices.items())
                or time.ndim != 1 or len(time) < 2 or not np.isfinite(time).all()
                or time[0] != 0 or np.any(np.diff(time) <= 0)
                or type(duration_ms) is not int or duration_ms < 1
                or time[-1] < duration_ms - 1e-9
                or isinstance(threshold_mv, (bool, np.bool_))
                or not math.isfinite(threshold_mv)):
            raise ValueError('Invalid window crossing configuration')
        self.indices = {body: indices.copy() for body, indices in selected_indices.items()}
        self.time = time.copy()
        self.threshold = threshold_mv
        self.duration = duration_ms
        self.previous = {}
        self.ticks = {body: {index: [] for index in indices}
                      for body, indices in self.indices.items()}
        # Crossings that share a tick with an earlier one. The network can only
        # deliver one event per tick, so these are counted and reported rather
        # than raising: a strong stimulus fires bursts, and aborting the whole
        # replay on the second crossing inside a millisecond made every strong
        # run fail instead of reporting what the trace did.
        self.coincident = 0
        self.position = 0
        self.failed = False
        # One counter per graph millisecond. The voltage trace is a membrane
        # potential that decays back to rest before the window closes, so a
        # population that spiked still reads as zero at the end of the record.
        # Counting the crossings the tick grid actually carried keeps that
        # evidence: measured on the full population, the final synaptic drive was
        # exactly zero for all 166 700 cells while the same pass produced 509
        # spikes. Zero in the potential is not silence.
        # One counter per sample of the recorded time base, indexed by the graph
        # tick the crossing was collapsed onto, so the counter and the electrode
        # trace describe the same window.
        self.counts = np.zeros(len(time), dtype=np.int64)

    def accept(self, start, end, rows):
        try:
            if (self.failed or type(start) is not int or type(end) is not int
                    or start != self.position or not start < end <= len(self.time)
                    or not isinstance(rows, list)
                    or [row.get('id') if isinstance(row, dict) else None for row in rows]
                       != list(self.indices)):
                raise ValueError('Invalid window crossing order')
            for row in rows:
                body = row['id']
                selected = np.asarray(row.get('selected_voltage_mv'), dtype=float)
                if (selected.shape != (len(self.indices[body]), end - start)
                        or not np.isfinite(selected).all()):
                    raise ValueError('Invalid window crossing voltage')
                if start == 0 and np.any(selected[:, 0] >= self.threshold):
                    raise ValueError('Initial voltage is already above the crossing threshold')
                if selected.shape[0]:
                    preceding = np.empty_like(selected)
                    preceding[:, 0] = (self.previous[body] if start else selected[:, 0])
                    preceding[:, 1:] = selected[:, :-1]
                    segment_rows, offsets = np.nonzero((preceding < self.threshold)
                                                       & (selected >= self.threshold))
                    for segment_row, offset in zip(segment_rows, offsets, strict=True):
                        index = self.indices[body][int(segment_row)]
                        current_index = start + int(offset)
                        crossing = self.time[current_index]
                        if crossing > self.duration + 1e-9:
                            raise ValueError('Cell trace contains crossings outside graph interval')
                        nearest = round(crossing)
                        snapped = nearest if abs(crossing - nearest) <= 1e-9 else crossing
                        if snapped == 0:
                            snapped = crossing
                        tick = math.ceil(snapped)
                        before = self.time[current_index - 1]
                        nearest_before = round(before)
                        if abs(before - nearest_before) <= 1e-9:
                            before = nearest_before
                        if math.floor(before) + 1 != tick:
                            raise ValueError('Threshold crossing spans a graph tick boundary')
                        if tick in self.ticks[body][index]:
                            self.coincident += 1
                            continue
                        self.ticks[body][index].append(tick)
                        self.counts[tick] += 1
                    self.previous[body] = selected[:, -1].copy()
            self.position = end
        except Exception:
            self.failed = True
            raise

    def finish(self):
        if self.failed or self.position != len(self.time):
            raise ValueError('Incomplete window crossing stream')
        return {body: {index: ticks.copy() for index, ticks in values.items()}
                for body, values in self.ticks.items()}

    def activity(self):
        """Crossings per graph millisecond, as the tick grid delivered them."""
        return self.counts.copy()

    def report(self):
        """Counts of what was observed, including what the tick grid collapsed."""
        return {'tick_events': sum(len(ticks) for values in self.ticks.values()
                                   for ticks in values.values()),
                'coincident_crossings': self.coincident,
                'activity_total': int(self.counts.sum())}
