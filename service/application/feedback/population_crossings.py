"""Collect provisional per-segment threshold events across bounded GPU batches."""

from service.application.feedback.outputs import feedback_selected_output_ticks
from service.infrastructure.stimulation.experimental_gpu.window_crossings import WindowedCrossings


class PopulationCrossings:
    """Stage model crossings; callers publish only after the whole replay succeeds.

    A threshold crossing in a selected segment is not proof of a cell spike.
    Segment-to-synapse mapping and graph transmission are separate operations.
    """

    def __init__(self, expected_ids, *, time_ms, threshold_mv, duration_ms):
        if (not isinstance(expected_ids, list) or not expected_ids
                or any(type(body) is not int or body <= 0 for body in expected_ids)
                or len(set(expected_ids)) != len(expected_ids)):
            raise ValueError('Invalid crossing population')
        self.expected = set(expected_ids)
        self.time = time_ms
        self.threshold = threshold_mv
        self.duration = duration_ms
        self.completed = {}
        self.active = None
        self.selection = None
        self.failed = False

    def accept(self, start, end, rows, selection):
        try:
            if (self.failed or not isinstance(selection, dict) or not selection
                    or any(not isinstance(indices, list) for indices in selection.values())):
                raise ValueError('Invalid population crossing batch')
            if start == 0:
                if (self.active is not None or any(type(body) is not int
                        or body not in self.expected or body in self.completed
                        for body in selection)):
                    raise ValueError('Invalid population crossing identities')
                self.selection = {body: indices.copy() for body, indices in selection.items()}
                self.active = WindowedCrossings(self.selection, time_ms=self.time,
                    threshold_mv=self.threshold, duration_ms=self.duration)
            elif self.active is None or selection != self.selection:
                raise ValueError('Population crossing selection changed')
            self.active.accept(start, end, rows)
            if end == len(self.time):
                self.completed.update(self.active.finish())
                self.active = self.selection = None
        except Exception:
            self.failed = True
            raise

    def finish(self):
        if self.failed or self.active is not None or set(self.completed) != self.expected:
            raise ValueError('Incomplete population crossings')
        return {body: {index: ticks.copy() for index, ticks in values.items()}
                for body, values in self.completed.items()}

    def verified_outputs(self, geometries, provenance, diagnostics, *,
                         max_source_distance_um=None):
        """Resolve completed crossings against caller-verified source geometry.

        The archive and morphology must be independently verified before this
        call. Results remain provisional until graph routing also succeeds.
        """
        crossings = self.finish()
        if any(not isinstance(value, dict) or set(value) != self.expected
               for value in (geometries, provenance, diagnostics)):
            raise ValueError('Inconsistent population output identities')
        return {body: feedback_selected_output_ticks(
            body, geometries[body]['edge_node_ids'], crossings[body],
            provenance[body], diagnostics[body], threshold_mv=self.threshold,
            duration_ms=self.duration, include_candidates=True,
            max_source_distance_um=max_source_distance_um)
            for body in crossings}
