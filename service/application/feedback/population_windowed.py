"""Experimental streaming adapter for selected physical-cell feedback events."""

import numpy as np

from service.infrastructure.stimulation.experimental_gpu.population_recording import (
    PopulationRecording,
)
from service.infrastructure.stimulation.experimental_gpu.window_crossings import WindowedCrossings

from .outputs import feedback_output_segment_indices, feedback_selected_output_ticks


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
        self.batch = None
        self.recording = PopulationRecording(expected_ids, electrode_um=electrode_um,
            reference_um=reference_um, conductivity_s_m=conductivity_s_m,
            clearance_um=clearance_um, samples=len(time), selection_factory=self._select,
            selected_sink=self._accept)

    def _select(self, cells):
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
        selection = {cell['id']: feedback_output_segment_indices(
            cell['id'], cell['geometry']['edge_node_ids'], provenance[cell['id']],
            diagnostics[cell['id']], threshold_mv=self.threshold, duration_ms=self.duration,
            max_source_distance_um=self.distance) for cell in cells}
        selector = WindowedCrossings(selection, time_ms=self.time, threshold_mv=self.threshold,
                                     duration_ms=self.duration)
        self.batch = (cells, provenance, diagnostics, selection, selector)
        return selection

    def _accept(self, start, end, rows, selection):
        if self.batch is None:
            raise ValueError('Missing population feedback batch')
        cells, provenance, diagnostics, expected, selector = self.batch
        if selection != expected:
            raise ValueError('Population feedback selection changed')
        selector.accept(start, end, rows)
        if end == len(self.time):
            ticks = selector.finish()
            results = {}
            for cell in cells:
                body = cell['id']
                results[body] = feedback_selected_output_ticks(body,
                    cell['geometry']['edge_node_ids'], ticks[body], provenance[body],
                    diagnostics[body], threshold_mv=self.threshold, duration_ms=self.duration,
                    include_candidates=True, include_unresolved_candidates=True,
                    max_source_distance_um=self.distance)
            self.event_sink(results)
            self.batch = None

    def factory(self, cells):
        return self.recording.factory(cells)

    def finish(self):
        return self.recording.finish()
