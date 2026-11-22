"""Experimental streaming adapter for selected physical-cell feedback events."""

import time

import numpy as np

from service.infrastructure.stimulation.experimental_gpu.population_recording import (
    PopulationRecording,
)
from service.infrastructure.stimulation.experimental_gpu.window_crossings import WindowedCrossings

from service.infrastructure.stimulation.population.source_columns import CandidateColumns

from service.infrastructure.stimulation.experimental_gpu.selection_cache import (
    HAS_CANDIDATES,
    HAS_PLACEHOLDERS,
)

from .outputs import feedback_output_plan, feedback_plan_output_ticks


def _output_plan(cell, provenance, diagnostic, *, threshold_mv, duration_ms,
                 max_source_distance_um):
    """Resolve one cell's outputs from whichever form the diagnostics came in."""
    body = cell['id']
    if isinstance(diagnostic, CandidateColumns):
        return diagnostic.plan(body, cell['geometry']['edge_node_ids'], provenance,
            threshold_mv=threshold_mv, duration_ms=duration_ms, include_candidates=True,
            include_unresolved_candidates=True,
            max_source_distance_um=max_source_distance_um)
    return feedback_output_plan(body, cell['geometry']['edge_node_ids'], provenance, diagnostic,
        threshold_mv=threshold_mv, duration_ms=duration_ms, include_candidates=True,
        include_unresolved_candidates=True, max_source_distance_um=max_source_distance_um)


class PopulationWindowedFeedback:
    """Stage numerical crossings batchwise; caller verifies all provenance and commits outputs."""

    def __init__(self, expected_ids, *, metadata_factory, event_sink, time_ms, threshold_mv,
                 duration_ms, electrode_um, reference_um, conductivity_s_m, clearance_um,
                 max_source_distance_um=None, resume=None, timing_sink=None,
                 coefficients=None, output_selection=None):
        time = np.asarray(time_ms, dtype=float)
        if (not callable(metadata_factory) or not callable(event_sink) or time.ndim != 1
                or len(time) < 2 or not np.isfinite(time).all() or np.any(np.diff(time) <= 0)
                or not np.isclose(time[0], 0., rtol=0, atol=1e-9)
                or not np.isclose(time[-1], duration_ms, rtol=0, atol=1e-9)):
            raise ValueError('Invalid population feedback time grid or callbacks')
        self.time = time.copy()
        self.metadata_factory = metadata_factory
        # The resolve stage is charged to the packer thread and measured as one
        # number, but it is two different costs: reading the durable payload and
        # computing the plan from it. Splitting them here is what tells whether
        # the remaining lever is storage or arithmetic.
        self.timing_sink = timing_sink
        self.event_sink = event_sink
        self.threshold = threshold_mv
        self.duration = duration_ms
        self.distance = max_source_distance_um
        # Batches are keyed by identity, not held in one slot: the selection is
        # resolved ahead of the solve, so a later batch may be staging while an
        # earlier one is still streaming windows. An entry is dropped exactly
        # when its last window arrives, so the map holds only work in flight.
        self.batches = {}

        # The selection - which compartments of each cell must come back as traces -
        # is a function of the verified sources, the threshold and the distance cut,
        # so it is read rather than recomputed when a table exists for this
        # preparation. Measured on the full population, recomputing it cost the
        # packer 355 s of a 1010 s pass and reading it 204 s of a 921 s pass.
        self.selection = output_selection

        self.recording = PopulationRecording(expected_ids, electrode_um=electrode_um,
            reference_um=reference_um, conductivity_s_m=conductivity_s_m,
            clearance_um=clearance_um, samples=len(time), selection_factory=self._select,
            selected_sink=self._accept, resume=resume, timing_sink=timing_sink,
            coefficients=coefficients)

    def _resolve(self, cells):
        """Resolve one batch's durable candidates into per-cell output plans.

        The batch resolution runs on whichever stage calls the factory, which is
        the population packer: it builds one batch's selection while the GPU is
        still solving the previous one. Resolving it on the solve thread instead
        put 27% of that thread's wall time in front of every launch (metadata
        5.98 s of a 92.44 s slice), and moving the durable read alone onto a
        separate thread measured worse (91.4 -> 111.6 s on 15 343 cells) because
        that second thread competed with the prepare stage instead of reusing an
        existing idle window.
        """
        ids = [cell['id'] for cell in cells]
        started = time.perf_counter()
        metadata = self.metadata_factory(cells)
        if self.timing_sink is not None:
            self.timing_sink('resolve_metadata', time.perf_counter() - started)
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
        started = time.perf_counter()
        plans = {cell['id']: _output_plan(cell, provenance[cell['id']], diagnostics[cell['id']],
                 threshold_mv=self.threshold, duration_ms=self.duration,
                 max_source_distance_um=self.distance) for cell in cells}
        if self.timing_sink is not None:
            self.timing_sink('resolve_plan', time.perf_counter() - started)
        return plans

    def _select(self, cells):
        ids = [cell['id'] for cell in cells]
        key = tuple(ids)
        if self.selection is None:
            plans = self._resolve(cells)
        elif self.selection.loaded:
            plans = self._resolve_from_table(cells)
        else:
            plans = self._resolve_and_record(cells)
        selection = {body: plan['indices'] for body, plan in plans.items()}
        selector = WindowedCrossings(selection, time_ms=self.time, threshold_mv=self.threshold,
                                     duration_ms=self.duration)
        self.batches[key] = (cells, plans, selection, selector)
        return selection

    def _resolve_from_table(self, cells):
        """Answer the solver from the stored selection, planning only what speaks.

        The solver needs one thing from the packer: which compartments of each
        cell to record. Everything else the plan carries - partner multiplicities
        and the candidate rows of every contact - is read only when a compartment
        actually crosses, and 166 697 of 166 700 cells cross nothing. Answering
        from the table therefore costs a slice and a copy per cell, and the real
        plan is built on the same thread only for the cell that has something to
        say, which is where the deferred resolver in the renderer asks for it.
        """
        started = time.perf_counter()
        plans = {}
        for cell in cells:
            body = cell['id']
            entry = self.selection.entry_for(body)
            if entry is None:
                # A cell the table does not cover is planned as it always was and
                # the table is not published: a partial answer would silently drop
                # compartments from the recording.
                plans.update(self._resolve([cell]))
                self.selection.note_incomplete()
                continue
            indices, flags = entry
            plans[body] = {
                'body': body, 'indices': indices, 'ticks': {value: [] for value in indices},
                'duration_ms': self.duration, 'include_candidates': True,
                # A cell whose compartments stayed quiet still records that its
                # candidate rows were withheld, and only a cell with no candidate
                # at all has nothing to withhold.
                'omitted': bool(flags & HAS_CANDIDATES),
                'deferred': True,
                'deferred_plan': self._plan_resolver(cell, flags)}
        if self.timing_sink is not None:
            self.timing_sink('resolve_plan', time.perf_counter() - started)
        return plans

    def _resolve_and_record(self, cells):
        """Plan a batch the old way and remember the selection for the next pass."""
        plans = self._resolve(cells)
        for cell in cells:
            plan = plans[cell['id']]
            rows = plan.get('rows')
            # The placeholder flag is the only fact the stored plan needs beyond
            # the compartments: an unresolved contact survives without crossing.
            self.selection.record(cell['id'], plan['indices'],
                                  placeholders=bool(hasattr(rows, 'has_placeholders')
                                                    and rows.has_placeholders()))
        return plans

    def _plan_resolver(self, cell, flags):
        """Return the callable a stored plan uses to build itself when it speaks."""
        body = cell['id']
        placeholders = bool(flags & HAS_PLACEHOLDERS)

        def resolve(ticks):
            if not placeholders and not any(ticks.values()):
                # Nothing crossed and nothing survives without crossing: the rows
                # this cell would have contributed are exactly what a compact
                # archive records by leaving them out.
                return None
            return self._resolve([cell])[body]

        return resolve

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
        # The recorder's coefficients are a function of the cell geometry alone,
        # but the constructor is charged to the resolve stage: on the full
        # population resolve measured 614 s while the durable read (92 s) and the
        # plan (212 s) together account for only half of it. Splitting this out
        # names the remainder instead of leaving it inside "resolve".
        started = time.perf_counter()
        recording = self.recording.factory(cells)
        if self.timing_sink is not None:
            self.timing_sink('resolve_factory', time.perf_counter() - started)
        return recording

    def finish(self):
        return self.recording.finish()