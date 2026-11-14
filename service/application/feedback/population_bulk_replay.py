"""Experimental bulk physical replay with staged feedback and electrode signal."""

import numpy as np

from service.infrastructure.stimulation.experimental_gpu.population_replay import solve_population

from .event_archive import EventArchive
from .population_windowed import PopulationWindowedFeedback


def replay_bulk_feedback(metadata, stimulus, rate_table, *, audited_sources, params, expected_ids,
                         events_by_target, metadata_factory, event_sink, time_ms, threshold_mv,
                         duration_ms, electrode_um, reference_um, conductivity_s_m, clearance_um,
                         segment_budget, output_budget_bytes, max_source_distance_um=None,
                         batch_progress=None,
                         **solver_options):
    """Replay a fixed schedule; event_sink must stage results until this function returns.

    ``events_by_target`` may be a batch callback to avoid materialising the
    entire network schedule; its results remain subject to caller verification.
    The caller owns graph/synapse and schedule verification. This is not a
    coupled-network iteration, a complete experiment, or a biological model.
    """
    if (not isinstance(expected_ids, list) or not expected_ids
            or any(type(body) is not int or body <= 0 for body in expected_ids)
            or len(set(expected_ids)) != len(expected_ids)
            or not (callable(events_by_target) or isinstance(events_by_target, dict))
            or (isinstance(events_by_target, dict)
                and (set(events_by_target) != set(expected_ids)
                     or any(not isinstance(events_by_target[body], list)
                            for body in expected_ids)))
            or not callable(metadata_factory) or not callable(event_sink)
            or (batch_progress is not None and not callable(batch_progress))
            or any(key in solver_options for key in ('event_factory', 'device_window_factory',
                                                     'window_sink'))):
        raise ValueError('Invalid bulk feedback replay inputs')
    dt = solver_options.get('dt_ms', .05)
    time = np.asarray(time_ms, dtype=float)
    if (type(dt) not in (int, float) or dt not in (.025, .05)
            or time.ndim != 1 or len(time) != len(stimulus)
            or not np.allclose(time, np.arange(len(time)) * dt, rtol=0, atol=1e-9)):
        raise ValueError('Bulk feedback time grid does not match GPU time step')
    collector = PopulationWindowedFeedback(expected_ids, metadata_factory=metadata_factory,
        event_sink=event_sink, time_ms=time_ms, threshold_mv=threshold_mv,
        duration_ms=duration_ms, electrode_um=electrode_um, reference_um=reference_um,
        conductivity_s_m=conductivity_s_m, clearance_um=clearance_um,
        max_source_distance_um=max_source_distance_um)

    def events_for_batch(batch):
        events = (events_by_target(batch) if callable(events_by_target)
                  else {body: events_by_target[body] for body in batch})
        if (not isinstance(events, dict) or set(events) != set(batch)
                or any(not isinstance(events[body], list) for body in batch)):
            raise ValueError('Invalid bulk feedback event batch')
        return events

    received = set()
    for ids, result in solve_population(metadata, stimulus, rate_table,
            audited_sources=audited_sources, params=params, segment_budget=segment_budget,
            output_budget_bytes=output_budget_bytes, device_window_factory=collector.factory,
            event_factory=events_for_batch,
            **solver_options):
        if result.get('table_clamped_cell_ids') != []:
            raise ValueError('Bulk feedback replay encountered clamped HH table values')
        if (not isinstance(ids, (list, tuple)) or not ids
                or any(type(body) is not int for body in ids)
                or len(set(ids)) != len(ids) or received.intersection(ids)
                or not set(ids).issubset(collector.recording.completed)):
            raise ValueError('Bulk feedback solver receipt does not match recorded cells')
        received.update(ids)
        if batch_progress is not None:
            batch_progress(len(received), len(expected_ids))
    signal = collector.finish()
    if received != collector.recording.completed:
        raise ValueError('Bulk feedback solver receipts are incomplete')
    return {'neural_uv': signal, 'cells': len(received),
            'interpretation': 'experimental fixed-schedule replay; no network convergence'}


def replay_bulk_feedback_to_archive(*args, event_path, **kwargs):
    """Publish streamed events only after the complete replay has been verified."""
    if 'event_sink' in kwargs:
        raise ValueError('Event archive owns the event sink')
    with EventArchive(event_path) as archive:
        result = replay_bulk_feedback(*args, event_sink=archive.write_batch, **kwargs)
        archive.commit()
        result['event_sha256'] = archive.sha256
    return result


def replay_verified_feedback_to_archive(metadata, stimulus, rate_table, *, schedule,
                                        schedule_sha256, morphology_sha256, event_path,
                                        metadata_factory, **options):
    """Replay a verified fixed schedule and atomically archive selected outputs.

    The caller supplies independently trusted schedule and morphology digests.
    This performs one replay, not recurrent convergence or biological validation.
    """
    from .fixed_inputs import fixed_input_factory

    if (not isinstance(metadata, dict) or not callable(metadata_factory)
            or 'events_by_target' in options or 'event_sink' in options):
        raise ValueError('Invalid verified feedback replay inputs')
    graph_sha256 = metadata.get('graph_sha256')
    event_factory = fixed_input_factory(schedule, options.get('expected_ids'),
        morphology_sha256, graph_sha256=graph_sha256,
        expected_schedule_sha256=schedule_sha256)
    # A one-segment GPU replay cannot place an event at a zero-area endpoint.
    # Check the whole authenticated schedule before spending time on batches;
    # never silently relocate the event without an audited grid policy.
    for body, events in schedule['events_by_target'].items():
        if any(isinstance(event, dict) and event.get('position') in (0, 1)
               and type(event.get('position')) in (int, float) for event in events):
            raise ValueError(f'Unresolved feedback endpoint in target cell {body}')
    frozen_hashes = morphology_sha256.copy()

    def checked_metadata(cells):
        if any(cell.get('morphology_sha256') != frozen_hashes.get(cell.get('id'))
               for cell in cells):
            raise ValueError('Verified feedback morphology digest mismatch')
        return metadata_factory(cells)

    result = replay_bulk_feedback_to_archive(metadata, stimulus, rate_table,
        event_path=event_path, events_by_target=event_factory,
        metadata_factory=checked_metadata, **options)
    result['fixed_input_schedule_sha256'] = schedule_sha256
    result['fixed_input_graph_sha256'] = graph_sha256
    return result
