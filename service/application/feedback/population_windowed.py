"""Experimental streaming adapter for selected physical-cell feedback events."""

import numpy as np

from service.infrastructure.stimulation.experimental_gpu.population_recording import (
    PopulationRecording,
)
from service.infrastructure.stimulation.experimental_gpu.window_crossings import WindowedCrossings

from .outputs import feedback_output_plan, feedback_plan_output_ticks


class PopulationWindowedFeedback:
    """Stage numerical crossings batchwise; caller verifies all provenance and commits outputs."""

    def __init__(self, expected_ids, *, metadata_factory, event_sink, time_ms, threshold_mv,
                 duration_ms, electrode_um, reference_um, conductivity_s_m, clearance_um,
                 max_source_distance_um=None):
        time = np.asarray(time_ms, dtype=float)
        if (not callable(metadata_factory) or not callable(event_sink) or time.ndim != 1
                or len(time) < 2 or not np.isfinite(time).all() or np.any(np.diff(time) <= 0)
                or not np.isclose(time[0], 0., rtol=0, atol=1e-9)
                or not np.isclose(time[-1], duration_ms, rtol=0, atol=1e-9)):
            raise ValueError('Invalid population feedback time grid or callbacks')
        self.time = time.copy()
        self.metadata_factory = metadata_factory
        self.event_sink = event_sink
        self.threshold = threshold_mv
        self.duration = duration_ms
        self.distance = max_source_distance_um
        # Batches are keyed by identity, not held in one slot: the selection is
        # resolved one batch ahead of the solve, so a later batch may be staging
        # while an earlier one is still streaming windows.
        self.batches = {}

        self.recording = PopulationRecording(expected_ids, electrode_um=electrode_um,
            reference_um=reference_um, conductivity_s_m=conductivity_s_m,
            clearance_um=clearance_um, samples=len(time), selection_factory=self._select,
            selected_sink=self._accept)

    def _resolve(self, cells):
        """Resolve one batch's durable candidates into per-cell output plans.

        The whole resolution is deliberately kept on the caller's thread: the
        durable read and the candidate walk are CPU-bound Python, and moving them
        one batch ahead onto a helper thread measured WORSE (91.4 -> 111.6 s on a
        15 343-cell slice) because the second thread only takes interpreter time
        from the prepare stage and the device starves.
        """
        ids = [cell['id'] for cell in cells]
        metadata = self.metadata_factory(cells)
        if (not isinstance(metadata, dict) or set(metadata) != {'provenance', 'diagnostics'}
                or not isinstance(metadata['provenance'], dict)
                or not isinstance(metadata['diagnostics'], dict)
                or list(metadata['provenance']) != ids or list(metadata['diagnostics']) != ids):
            raise ValueError('Invalid population feedback metadata')
        provenance, diagnostics = metadata['provenance'], metadata['diagnostics']
        if any(not isinstance(provenance[body], dict)
               or cell.get('morphology_sha256') != provenance[body].get('morphology_sha256')
               for body, cell in zip(ids, cells, strict=True)):
            raise ValueError('Population feedback morphology identity mismatch')
        # Resolve each cell's durable candidates once and keep the resolved plan:
        # the tick pass at the end of the batch reuses it instead of walking the
        # candidate list a second time (that duplicate walk cost 26 s of a 130 s
        # slice on 15 343 cells).
        return {cell['id']: feedback_output_plan(
            cell['id'], cell['geometry']['edge_node_ids'], provenance[cell['id']],
            diagnostics[cell['id']], threshold_mv=self.threshold, duration_ms=self.duration,
            include_candidates=True, include_unresolved_candidates=True,
            max_source_distance_um=self.distance) for cell in cells}

    def _select(self, cells):
        ids = [cell['id'] for cell in cells]
        key = tuple(ids)
        plans = self._resolve(cells)
        selection = {body: plan['indices'] for body, plan in plans.items()}
        selector = WindowedCrossings(selection, time_ms=self.time, threshold_mv=self.threshold,
                                     duration_ms=self.duration)
        self.batches[key] = (cells, plans, selection, selector)
        while len(self.batches) > 2:
            self.batches.pop(next(iter(self.batches)))
        return selection

    def _accept(self, start, end, rows, selection):
        key = tuple(row.get('id') if isinstance(row, dict) else None for row in rows)
        if self.batches.get(key) is None:
            raise ValueError('Missing population feedback batch')
        cells, plans, expected, selector = self.batches[key]
        if selection != expected:
            raise ValueError('Population feedback selection changed')
        selector.accept(start, end, rows)
        if end == len(self.time):
            ticks = selector.finish()
            results = {cell['id']: feedback_plan_output_ticks(plans[cell['id']], ticks[cell['id']])
                       for cell in cells}
            self.event_sink(results)
            self.batches.pop(key, None)

    def factory(self, cells):
        return self.recording.factory(cells)

    def finish(self):
        return self.recording.finish()
