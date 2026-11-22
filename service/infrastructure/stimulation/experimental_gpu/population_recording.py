"""Bounded accumulation of experimental population electrode recordings."""

import threading
import time

import numpy as np

from .window_recording import WindowedPointRecorder

# A coefficient store that fails this many times is dropped for the rest of the
# pass: a broken store must not cost one failed read per batch forever.
_CACHE_ERROR_LIMIT = 4


class PopulationRecording:
    """Accumulate independent currents and optionally stream selected voltages.

    Selected-window sinks receive provisional data: callers must stage it and
    publish only after the entire solver and ``finish`` have both succeeded.
    This helper does not establish network coupling.
    """

    def __init__(self, expected_ids, *, electrode_um, reference_um, conductivity_s_m,
                 clearance_um, samples, selection_factory=None, selected_sink=None,
                 resume=None, timing_sink=None, coefficients=None):
        """Accumulate one pass, optionally continuing a paused one.

        ``resume`` carries the cells a paused pass had already recorded and the
        signal they produced, so a resumed pass adds to that record instead of
        starting a new one. The cells are then simply no longer expected: the
        pass covers the remainder and its signal is the whole population's.
        """
        if (not isinstance(expected_ids, (list, tuple)) or not expected_ids
                or any(type(body) is not int or body <= 0 for body in expected_ids)
                or len(set(expected_ids)) != len(expected_ids)
                or type(samples) is not int or samples < 2
                or (selection_factory is None) != (selected_sink is None)
                or (selection_factory is not None and not callable(selection_factory))
                or (selected_sink is not None and not callable(selected_sink))
                or (resume is not None and not isinstance(resume, dict))):
            raise ValueError('Invalid population recording identities or samples')
        self.expected = set(expected_ids)
        self.completed = set()
        self.signal = np.zeros(samples, dtype=float)
        self.resumed = 0
        if resume is not None:
            done = resume.get('done_ids')
            signal = resume.get('signal')
            if (not isinstance(done, set) or not done or not done.issubset(self.expected)
                    or not isinstance(signal, np.ndarray) or signal.shape != (samples,)
                    or not np.isfinite(signal).all()):
                raise ValueError('Invalid population recording resume state')
            self.completed = set(done)
            self.signal = signal.astype(float, copy=True)
            self.resumed = len(done)
        self.electrode = electrode_um
        self.reference = reference_um
        self.conductivity = conductivity_s_m
        self.clearance = clearance_um
        self.samples = samples
        # A batch's selection is resolved ahead of its solve, so several batches
        # can legitimately be in flight: one streaming windows, one packed, and
        # up to the prepare window still being planned. They are therefore keyed
        # by identity instead of sharing a single slot, and a repeat of a batch
        # already in flight is still rejected rather than silently reopened.
        self.inflight = {}
        # Windows are delivered on their own thread, so the receipt that the
        # solver hands back can be read while another batch is still streaming:
        # both views of the batch table are therefore taken under one lock.
        self._lock = threading.Lock()
        self.failed = False
        self.selection_factory = selection_factory
        self.selected_sink = selected_sink
        # Optional durable store of the per-batch recording coefficients. They are
        # a function of the reduced geometry and the electrode pair, they are
        # recomputed on every pass, and their construction measured 159.8 s of a
        # 384 s tail shard while removing it entirely saved 96 s.
        self.coefficients = coefficients
        # What the store actually did, for the pass receipt: a hit and a miss are
        # different amounts of work, and a run that only recomputed must not be
        # reported as one that replayed.
        self.coefficient_hits = 0
        self.coefficient_misses = 0
        self.coefficient_errors = 0
        # The recorder is separable from the selection: one is geometry (the
        # per-segment field coefficients this batch will be recorded with), the
        # other is the durable plan. Both are charged to the packer, so they are
        # timed apart before either is optimised.
        self.timing_sink = timing_sink

    def _cached_coefficients(self, geometries, morphologies):
        """Coefficients for this batch, from the durable store when it has them.

        A cache is an optimisation, so no cache failure may fail a pass: any
        error there is counted and the batch falls back to computing its own
        coefficients exactly as it did before the store existed. After a few
        failures the store is dropped for the rest of the pass instead of paying
        a broken read per batch.
        """
        if self.coefficients is None:
            return None
        if any(not isinstance(value, str) for value in morphologies.values()):
            return None
        if self.coefficient_errors >= _CACHE_ERROR_LIMIT:
            self.coefficients = None
            return None
        try:
            # The key names the cells and the preparation: the reduced geometry of
            # a cell is a deterministic function of its morphology digest and the
            # params, so those two cover it without hashing 88 bytes per segment.
            key = self.coefficients.key_for(geometries, morphologies=morphologies,
                                            electrode_um=self.electrode,
                                            reference_um=self.reference,
                                            conductivity_s_m=self.conductivity,
                                            clearance_um=self.clearance)
            cached = self.coefficients.get(key, list(geometries))
            if cached is not None:
                self.coefficient_hits += 1
                return cached
            self.coefficient_misses += 1
            # A miss hands the coefficients back as a side effect: the pass
            # computes them anyway, so it fills the cache it just missed.
            cached = self.coefficients.compute(geometries, electrode_um=self.electrode,
                                               reference_um=self.reference,
                                               conductivity_s_m=self.conductivity,
                                               clearance_um=self.clearance)
            self.coefficients.put(key, list(geometries), cached)
            return cached
        except Exception:
            # Counting must not itself raise: a broken store is a reason to fall
            # back to computing the batch, never a reason to fail the pass.
            self.coefficient_errors += 1
            if self.coefficient_errors >= _CACHE_ERROR_LIMIT:
                self.coefficients = None
            return None

    def factory(self, cells):
        if self.failed or not isinstance(cells, list) or not cells:
            raise ValueError('Invalid population recording batch state')
        ids = [cell.get('id') if isinstance(cell, dict) else None for cell in cells]
        if (any(type(body) is not int for body in ids) or len(set(ids)) != len(ids)
                or any(body not in self.expected or body in self.completed for body in ids)):
            raise ValueError('Invalid population recording batch identities')
        started = time.perf_counter()
        geometries = {cell['id']: cell['geometry'] for cell in cells}
        # The key is the cells' identity, and a prepared cell carries its
        # morphology digest only when the pass records: a batch without one simply
        # computes its coefficients, exactly as it did before the store existed.
        morphologies = {cell['id']: cell.get('morphology_sha256') for cell in cells}
        cached = self._cached_coefficients(geometries, morphologies)
        recorder = WindowedPointRecorder(geometries,
            self.electrode, self.reference, self.conductivity, clearance_um=self.clearance,
            samples=self.samples, coefficients=cached)
        if self.timing_sink is not None:
            self.timing_sink('resolve_recorder', time.perf_counter() - started)
        started = time.perf_counter()
        selection = ({body: [] for body in ids} if self.selection_factory is None
                     else self.selection_factory(cells))
        if self.timing_sink is not None:
            self.timing_sink('resolve_selection', time.perf_counter() - started)
        if (not isinstance(selection, dict) or list(selection) != ids
                or any(not isinstance(selection[body], list)
                       or any(type(index) is not int or not 0 <= index <
                              len(recorder.coefficients[body]) for index in selection[body])
                       or len(set(selection[body])) != len(selection[body]) for body in ids)):
            raise ValueError('Invalid population segment selection')
        key = tuple(ids)
        with self._lock:
            if key in self.inflight:
                raise ValueError('Invalid population recording batch identities')
            self.inflight[key] = None
        position = 0
        live = [True]

        def accept(start, end, rows):
            nonlocal position
            try:
                if (not live[0] or type(start) is not int or type(end) is not int
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
                    live[0] = False
                    with self._lock:
                        self.completed.update(ids)
                        self.inflight.pop(key, None)
            except Exception:
                self.failed = True
                raise

        return {'recording_coefficients': recorder.coefficients,
                'selected_indices': selection, 'sink': accept}

    def settled(self):
        """Snapshot of the cells already recorded or still streaming right now."""
        with self._lock:
            return self.completed.union(body for key in self.inflight for body in key)

    def finish(self):
        with self._lock:
            unsettled = bool(self.inflight) or self.completed != self.expected
        if self.failed or unsettled:
            raise ValueError('Incomplete population recording')
        return self.signal.copy()