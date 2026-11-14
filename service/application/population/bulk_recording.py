"""Independent detailed-population GPU replay with differential recording.

This is an experimental numerical component, not a coupled CNS simulation.
"""

import copy

import numpy as np

from service.infrastructure.stimulation.experimental_gpu.population_recording import (
    PopulationRecording,
)
from service.infrastructure.stimulation.experimental_gpu.population_replay import solve_population


def run_bulk_recording(metadata, stimulus, rate_table, *, audited_sources, params, expected_ids,
                       time_ms, electrode_um, reference_um, conductivity_s_m, clearance_um,
                       segment_budget, output_budget_bytes, progress=None,
                       _fixed_event_factory=None, _selection_factory=None,
                       _selected_sink=None, _max_selected=0, **solver_options):
    """Accumulate E1–REF for all expected independent cells or fail closed.

    Caller must separately establish provenance, calibration and publication
    policy. No network transmission or physiological validity is inferred.
    """
    if any(key in solver_options for key in ('device_window_factory', 'window_sink', 'on_invalid',
                                              'event_factory')):
        raise ValueError('Independent population recording owns solver callbacks')
    if _fixed_event_factory is not None and not callable(_fixed_event_factory):
        raise ValueError('Invalid fixed input provider')
    if (type(_max_selected) is not int or _max_selected < 0
            or (_selection_factory is None) != (_selected_sink is None)
            or (_selection_factory is None and _max_selected != 0)
            or (_selection_factory is not None and
                (not callable(_selection_factory) or not callable(_selected_sink)))):
        raise ValueError('Invalid selected population output')
    dt = solver_options.get('dt_ms', .05)
    times = np.asarray(time_ms, dtype=float)
    if (type(dt) not in (int, float) or dt not in (.025, .05) or times.ndim != 1
            or len(times) != len(stimulus) or len(times) < 2
            or not np.allclose(times, np.arange(len(times)) * dt, rtol=0, atol=1e-9)):
        raise ValueError('Population recording time grid does not match solver')
    collector = PopulationRecording(expected_ids, electrode_um=electrode_um,
        reference_um=reference_um, conductivity_s_m=conductivity_s_m,
        clearance_um=clearance_um, samples=len(times), selection_factory=_selection_factory,
        selected_sink=_selected_sink)
    if progress is not None and not callable(progress):
        raise ValueError('Invalid population progress callback')
    if progress is not None:
        progress('independent_cells', 0, len(expected_ids))
    replacements = []
    if solver_options.get('replacement_factory') is not None:
        external_handler = solver_options.get('on_replacement')
        if external_handler is not None and not callable(external_handler):
            raise ValueError('Invalid replacement receipt callback')

        def record_replacement(body, code, receipt):
            replacements.append({'body_id': body, 'error_code': code,
                                 'transformation': copy.deepcopy(receipt)})
            if external_handler is not None:
                external_handler(body, code, receipt)

        solver_options['on_replacement'] = record_replacement
    received = set()
    for ids, receipt in solve_population(metadata, stimulus, rate_table,
            audited_sources=audited_sources, params=params, segment_budget=segment_budget,
            output_budget_bytes=output_budget_bytes, device_window_factory=collector.factory,
            recording_max_selected=_max_selected, event_factory=_fixed_event_factory,
            **solver_options):
        if not isinstance(receipt, dict) or receipt.get('table_clamped_cell_ids') != []:
            raise ValueError('Population solver encountered clamped or missing HH receipt')
        if (not isinstance(ids, (list, tuple)) or not ids
                or any(type(body) is not int for body in ids)
                or len(set(ids)) != len(ids) or received.intersection(ids)
                or not set(ids).issubset(collector.completed)):
            raise ValueError('Population solver receipt does not match recorded cells')
        received.update(ids)
        if progress is not None:
            progress('independent_cells', len(received), len(expected_ids))
    signal = collector.finish()
    if received != collector.completed:
        raise ValueError('Population solver receipts are incomplete')
    interpretation = ('independent detailed cells; no network feedback; '
                      'model parameters are not biologically validated')
    if _fixed_event_factory is not None:
        interpretation = ('fixed external event schedule; no network feedback; '
                          'model parameters are not biologically validated')
    return {'time_ms': times.copy(), 'neural_uv': signal, 'cells': len(received),
            'replacement_receipts': replacements,
            'interpretation': interpretation}


def run_fixed_input_recording(metadata, stimulus, rate_table, *, event_factory, **options):
    """Experimental fixed inputs; caller must verify graph and input provenance.

    This is not a coupled network solver. Never expose unchecked callbacks to users.
    Selected voltage windows are provisional until the entire call succeeds;
    a caller publishing them must stage and discard them on failure.
    """
    if not callable(event_factory) or '_fixed_event_factory' in options:
        raise ValueError('Invalid fixed input provider')
    return run_bulk_recording(metadata, stimulus, rate_table,
                              _fixed_event_factory=event_factory, **options)


def run_verified_fixed_input_recording(metadata, stimulus, rate_table, *, schedule,
                                       schedule_sha256, morphology_sha256, **options):
    """Replay an authenticated candidate schedule; no recurrent solve is implied."""
    from service.application.feedback.fixed_inputs import fixed_input_factory

    if not isinstance(metadata, dict):
        raise ValueError('Invalid fixed input metadata')
    graph_sha256 = metadata.get('graph_sha256')
    factory = fixed_input_factory(schedule, options.get('expected_ids'), morphology_sha256,
                                 graph_sha256=graph_sha256,
                                 expected_schedule_sha256=schedule_sha256)
    result = run_fixed_input_recording(metadata, stimulus, rate_table,
                                       event_factory=factory, **options)
    result['fixed_input_schedule_sha256'] = schedule_sha256
    result['fixed_input_graph_sha256'] = graph_sha256
    return result
