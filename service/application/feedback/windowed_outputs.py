"""Experimental bounded collection of physical source outputs and recording."""

import re
import time as clock

import numpy as np

from service.infrastructure.stimulation.experimental_gpu.window_recording import (
    WindowedPointRecorder,
)
from service.infrastructure.stimulation.experimental_gpu.window_traces import WindowedTraceSelector

from .outputs import feedback_output_segment_indices, feedback_selected_output_events


class WindowedFeedbackOutputs:
    """Collect selected outgoing traces and electrode signal for a verified group.

    The caller must independently verify the archive, morphology and replay
    configuration. This helper does not establish physiological validity.
    """

    def __init__(self, geometries, provenance, diagnostics, *, threshold_mv, duration_ms,
                 samples, electrode_um, reference_um, conductivity_s_m, clearance_um,
                 max_source_distance_um=None, resolved_indices=None):
        if (not isinstance(geometries, dict) or not geometries
                or not isinstance(provenance, dict) or not isinstance(diagnostics, dict)
                or list(geometries) != list(provenance) or list(geometries) != list(diagnostics)):
            raise ValueError('Inconsistent window feedback identities')
        self.ids = list(geometries)
        self.geometries = geometries
        self.provenance = provenance
        self.diagnostics = diagnostics
        self.threshold = threshold_mv
        self.duration = duration_ms
        self.max_source_distance_um = max_source_distance_um
        self.failed = False
        self.mode = None
        self.reduced_signal = np.zeros(samples, dtype=float)
        if resolved_indices is None:
            indices = {body: feedback_output_segment_indices(
                body, geometries[body]['edge_node_ids'], provenance[body], diagnostics[body],
                threshold_mv=threshold_mv, duration_ms=duration_ms,
                max_source_distance_um=max_source_distance_um) for body in self.ids}
        else:
            if (not isinstance(resolved_indices, dict)
                    or list(resolved_indices) != self.ids):
                raise ValueError('Inconsistent resolved output identities')
            indices = {body: resolved_indices[body].copy() for body in self.ids}
        self.indices = indices
        self.traces = WindowedTraceSelector(
            {body: len(geometries[body]['edge_node_ids']) for body in self.ids}, indices,
            samples=samples)
        self.recording = WindowedPointRecorder(geometries, electrode_um, reference_um,
            conductivity_s_m, clearance_um=clearance_um, samples=samples)

    def accept(self, start, end, rows):
        if self.failed:
            raise ValueError('Window feedback collector has failed')
        if self.mode not in (None, 'full'):
            raise ValueError('Cannot mix window recording modes')
        self.mode = 'full'
        try:
            self.traces.accept(start, end, rows)
            self.recording.accept(start, end, rows)
        except Exception:
            self.failed = True
            raise

    def accept_reduced(self, start, end, rows):
        if self.failed:
            raise ValueError('Window feedback collector has failed')
        if self.mode not in (None, 'reduced'):
            raise ValueError('Cannot mix window recording modes')
        self.mode = 'reduced'
        try:
            self.traces.accept_selected(start, end, rows)
            signal = np.zeros(end - start, dtype=float)
            for row in rows:
                values = np.asarray(row.get('neural_uv'), dtype=float)
                if values.shape != signal.shape or not np.isfinite(values).all():
                    raise ValueError('Invalid reduced recording window')
                signal += values
            if not np.isfinite(signal).all():
                raise ValueError('Non-finite reduced recording window')
            self.reduced_signal[start:end] = signal
        except Exception:
            self.failed = True
            raise

    def finish(self, time_ms):
        if self.failed:
            raise ValueError('Window feedback collector has failed')
        time = np.asarray(time_ms, dtype=float)
        if (time.ndim != 1 or len(time) != self.traces.samples or not np.isfinite(time).all()
                or np.any(np.diff(time) <= 0) or not np.isclose(time[0], 0., rtol=0, atol=1e-9)
                or not np.isclose(time[-1], self.duration, rtol=0, atol=1e-9)):
            raise ValueError('Invalid window feedback time grid')
        traces = self.traces.finish()
        output = {}
        for body in self.ids:
            selected = {index: trace for index, trace in
                        zip(self.indices[body], traces[body], strict=True)}
            output[body] = feedback_selected_output_events(
                body, time, self.geometries[body]['edge_node_ids'], selected,
                self.provenance[body], self.diagnostics[body], threshold_mv=self.threshold,
                duration_ms=self.duration, include_candidates=True,
                max_source_distance_um=self.max_source_distance_um)
        neural = self.reduced_signal.copy() if self.mode == 'reduced' else self.recording.finish()
        return {'neural_uv': neural, 'sources': output}


def solve_windowed_feedback(cells, provenance, diagnostics, stimulus, table, *, threshold_mv,
                            duration_ms, electrode_um, reference_um, conductivity_s_m,
                            clearance_um, max_cells, output_budget_bytes, window_steps,
                            max_padding_ratio, dt_ms, allow_table_clamp=False,
                            max_source_distance_um=None, packing_cache=None,
                            device_reduction=False, timing_sink=None, cell_major=False):
    """Experimental source-cell replay; no network iteration or artifact is added.

    Inputs must already be checked against the source archive and stimulation
    configuration. Prepared geometry is retained by the caller, so output
    limits do not bound total memory. Do not publish this diagnostic result.
    """
    from service.infrastructure.stimulation.experimental_gpu.window_batches import (
        solve_windowed_groups,
    )

    if (not isinstance(cells, list) or not cells or not isinstance(provenance, dict)
            or not isinstance(diagnostics, dict) or type(device_reduction) is not bool
            or type(cell_major) is not bool or (cell_major and not device_reduction)
            or (timing_sink is not None and not callable(timing_sink))
            or any(not isinstance(cell, dict) or type(cell.get('id')) is not int or cell['id'] <= 0
                   for cell in cells)):
        raise ValueError('Invalid window feedback source cells')
    ids = [cell['id'] for cell in cells]
    if (len(ids) != len(set(ids)) or set(ids) != set(provenance) or set(ids) != set(diagnostics)
            or any(not isinstance(provenance[body], dict) for body in ids)
            or any(not isinstance(cells[index].get('morphology_sha256'), str)
                   or not re.fullmatch('[a-f0-9]{64}', cells[index]['morphology_sha256'])
                   or provenance[body].get('morphology_sha256')
                      != cells[index]['morphology_sha256'] for index, body in enumerate(ids))):
        raise ValueError('Window feedback source identity mismatch')
    collectors = {}
    resolved_indices = None
    if cell_major:
        resolved_indices = {body: feedback_output_segment_indices(
            body, cells[index]['geometry']['edge_node_ids'], provenance[body], diagnostics[body],
            threshold_mv=threshold_mv, duration_ms=duration_ms,
            max_source_distance_um=max_source_distance_um) for index, body in enumerate(ids)}

    def get_collector(indices):
        if indices not in collectors:
            group_ids = [ids[index] for index in indices]
            collectors[indices] = WindowedFeedbackOutputs(
                {ids[index]: cells[index]['geometry'] for index in indices},
                {body: provenance[body] for body in group_ids},
                {body: diagnostics[body] for body in group_ids}, threshold_mv=threshold_mv,
                duration_ms=duration_ms, samples=len(stimulus), electrode_um=electrode_um,
                reference_um=reference_um, conductivity_s_m=conductivity_s_m,
                clearance_um=clearance_um, max_source_distance_um=max_source_distance_um,
                resolved_indices=({body: resolved_indices[body] for body in group_ids}
                                  if resolved_indices is not None else None))
        return collectors[indices]

    def accept(indices, start, end, rows):
        get_collector(indices).accept(start, end, rows)

    def device_factory(indices):
        collector = get_collector(indices)
        return {'recording_coefficients': collector.recording.coefficients,
                'selected_indices': collector.indices, 'sink': collector.accept_reduced}

    selection_counts = None
    if cell_major:
        selection_counts = [len(resolved_indices[body]) for body in ids]
    solved = solve_windowed_groups(cells, stimulus, table, max_cells=max_cells,
        output_budget_bytes=output_budget_bytes, window_steps=window_steps,
        max_padding_ratio=max_padding_ratio,
        **({'device_window_factory': device_factory} if device_reduction
           else {'window_sink': accept}),
        dt_ms=dt_ms, **({'cell_major': True, 'cell_major_selection_counts': selection_counts}
                       if cell_major else {}),
        allow_table_clamp=allow_table_clamp, packing_cache=packing_cache, timing_sink=timing_sink)
    collected_indices = [index for group in collectors for index in group]
    if (len(collected_indices) != len(ids)
            or set(collected_indices) != set(range(len(ids)))):
        raise ValueError('Incomplete window feedback groups')
    neural = np.zeros(len(stimulus), dtype=float)
    sources = {}
    for indices in sorted(collectors, key=lambda group: min(group)):
        group = collectors[indices].finish(solved['time_ms'])
        neural += group['neural_uv']
        sources.update(group['sources'])
    if not np.isfinite(neural).all() or set(sources) != set(ids):
        raise ValueError('Invalid aggregate window feedback')
    return {'time_ms': solved['time_ms'], 'neural_uv': neural,
            'sources': {body: sources[body] for body in ids},
            'table_clamped_cell_ids': solved['table_clamped_cell_ids'],
            'interpretation': 'experimental independent source-cell replay; '
                              'no network feedback or stimulation artifact'}


def solve_checked_windowed_feedback(cells, provenance, diagnostics, stimulus, table, *,
                                    stimulation_config, **kwargs):
    """Check cell stimulation before replay and append one direct artifact.

    Archive identity and connectivity must be verified by the caller. This is
    an internal diagnostic, not a published or closed-loop network result.
    """
    from service.infrastructure.stimulation.experimental_gpu.recording_adapter import (
        attach_windowed_artifact,
    )

    if (not isinstance(stimulation_config, dict) or not isinstance(cells, list) or not cells
            or not isinstance(provenance, dict) or type(kwargs.get('dt_ms')) not in (int, float)
            or kwargs['dt_ms'] not in (.025, .05)
            or type(kwargs.get('duration_ms')) not in (int, float)
            or not np.isfinite(kwargs['duration_ms']) or kwargs['duration_ms'] <= 0
            or not isinstance(stimulus, list | tuple | np.ndarray) or len(stimulus) < 2):
        raise ValueError('Invalid checked window feedback configuration')
    config = {**stimulation_config, 'dt_ms': kwargs['dt_ms']}
    timing_sink = kwargs.get('timing_sink')
    if timing_sink is not None and not callable(timing_sink):
        raise ValueError('Invalid checked window timing sink')
    time = np.arange(len(stimulus), dtype=float) * kwargs['dt_ms']
    if (not np.isclose(time[-1], kwargs.get('duration_ms'), rtol=0, atol=1e-9)
            or config.get('duration_ms') != kwargs.get('duration_ms')
            or config.get('conductivity_s_m') != kwargs.get('conductivity_s_m')
            or config.get('clearance_um') != kwargs.get('clearance_um')):
        raise ValueError('Window feedback and stimulation configuration mismatch')
    check_start = clock.perf_counter()
    for cell in cells:
        proof = provenance.get(cell.get('id'), {})
        source_config = proof.get('configuration') if isinstance(proof, dict) else None
        if (not isinstance(source_config, dict)
                or any(source_config.get(key) != value for key, value in config.items())
                or source_config.get('synaptic_events') != cell.get('events')):
            raise ValueError('Window feedback stimulation provenance mismatch')
    # Validate the field and waveform once, before the expensive solve.
    # Reuse that exact artifact afterwards rather than traversing every
    # morphology's junctions a second time.
    checked = attach_windowed_artifact(
        {'time_ms': time, 'neural_uv': np.zeros(len(time)),
         'sources': {cell['id']: {} for cell in cells}}, cells, config=config,
        stimulus_midpoint=stimulus, electrode_um=kwargs['electrode_um'],
        reference_um=kwargs['reference_um'])
    if timing_sink is not None:
        timing_sink('check_field_and_artifact', clock.perf_counter() - check_start)
    replay = solve_windowed_feedback(cells, provenance, diagnostics, stimulus, table, **kwargs)
    neural = np.asarray(replay.get('neural_uv'), dtype=float)
    if (not np.array_equal(replay.get('time_ms'), time)
            or list(replay.get('sources', {})) != [cell['id'] for cell in cells]
            or neural.shape != time.shape or not np.isfinite(neural).all()):
        raise ValueError('Invalid checked window feedback result')
    total = neural + checked['stimulus_artifact_uv']
    if not np.isfinite(total).all():
        raise ValueError('Non-finite checked window feedback result')
    return {**replay, 'stimulus_fraction': checked['stimulus_fraction'],
            'stimulus_artifact_uv': checked['stimulus_artifact_uv'], 'total_uv': total}
