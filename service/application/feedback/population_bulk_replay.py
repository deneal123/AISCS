"""Experimental bulk physical replay with staged feedback and electrode signal."""

import numpy as np

from service.infrastructure.stimulation.experimental_gpu.population_replay import solve_population

from .event_archive import EventArchive
from .pause import ReplayPaused, capture_state
from .population_windowed import PopulationWindowedFeedback


def replay_bulk_feedback(metadata, stimulus, rate_table, *, audited_sources, params, expected_ids,
                         events_by_target, metadata_factory, event_sink, time_ms, threshold_mv,
                         duration_ms, electrode_um, reference_um, conductivity_s_m, clearance_um,
                         segment_budget, output_budget_bytes, max_source_distance_um=None,
                         batch_progress=None, narrow_cache=None, pause=None,
                         archive=None, resume=None, pause_context=None,
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
                                                     'window_sink', 'narrow_cache', 'resume'))
            or (pause is not None and not callable(getattr(pause, 'check', None)))
            or (pause is not None and archive is None)
            or (pause is not None and not isinstance(pause_context, dict))
            or (resume is not None and not isinstance(resume, dict))):
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
        max_source_distance_um=max_source_distance_um, resume=resume)

    def events_for_batch(batch):
        events = (events_by_target(batch) if callable(events_by_target)
                  else {body: events_by_target[body] for body in batch})
        if (not isinstance(events, dict) or set(events) != set(batch)
                or any(not isinstance(events[body], list) for body in batch)):
            raise ValueError('Invalid bulk feedback event batch')
        return events

    kernels = {'accelerated_cell_major': 0, 'generic': 0, 'batches': 0}
    received = set() if resume is None else set(resume['done_ids'])
    # Batches already recorded by the pass being continued: the skip is
    # positional, so the resumed pass rebuilds the same batch sequence and only
    # leaves out the prefix that is already in the archive and the signal.
    resumed_batches = 0 if resume is None else int(resume['batches'])
    # One pass, one source: a cache hit replays already-narrowed cells, a miss
    # narrows them here and publishes the entry only once the pass has finished.
    source_store = None if narrow_cache is None else narrow_cache.store
    source_writer = None if narrow_cache is None else narrow_cache.writer
    for ids, result in solve_population(metadata, stimulus, rate_table,
            audited_sources=audited_sources, params=params, segment_budget=segment_budget,
            output_budget_bytes=output_budget_bytes, device_window_factory=collector.factory,
            event_factory=events_for_batch, narrow_cache=source_store,
            narrow_cache_writer=source_writer, resume=resume,
            **solver_options):
        if result.get('table_clamped_cell_ids') != []:
            raise ValueError('Bulk feedback replay encountered clamped HH table values')
        # Window delivery is asynchronous: a batch's last window may still be in
        # the recording pipeline when the solver hands back its receipt, so a cell
        # is accounted for as soon as it is either finished or still in flight.
        settled = collector.recording.settled()
        if (not isinstance(ids, (list, tuple)) or not ids
                or any(type(body) is not int for body in ids)
                or len(set(ids)) != len(ids) or received.intersection(ids)
                or not set(ids).issubset(settled)):
            raise ValueError('Bulk feedback solver receipt does not match recorded cells')
        kernels['batches'] += 1
        kernels['accelerated_cell_major' if result['accelerated_cell_major'] else 'generic'] += 1
        received.update(ids)
        if batch_progress is not None:
            batch_progress(len(received), len(expected_ids))
        if pause is not None and pause.check():
            # The boundary is the only honest place to stop: the archive holds
            # whole batches, every window of them has landed, and the signal
            # carries exactly those cells. What is written here is a pass that
            # can be continued, not a finished one.
            signal = collector.recording.signal.copy()
            batches = resumed_batches + kernels['batches']

            def capture(state):
                return capture_state(state, archive=archive, signal=signal,
                    done_ids=received, cells=len(received), batches=batches,
                    receipts=pause_context.get('receipts'),
                    archives=pause_context.get('archives'))

            meta = pause.save(phase=pause_context['phase'], capture=capture,
                iteration=pause_context.get('iteration'),
                history=pause_context.get('history'),
                previous=pause_context.get('previous'))
            raise ReplayPaused(meta)
    signal = collector.finish()
    if received != collector.recording.completed:
        raise ValueError('Bulk feedback solver receipts are incomplete')
    if narrow_cache is not None:
        # Published only now: an entry that covers a pass which failed verification
        # would let a later run skip the computation that produced its own evidence.
        narrow_cache.commit()
    receipt = {'neural_uv': signal, 'cells': len(received),
               'solver_kernels': kernels,
               'interpretation': 'experimental fixed-schedule replay; no network convergence'}
    if narrow_cache is not None:
        receipt['narrow_cache'] = narrow_cache.receipt()
    return receipt


def replay_bulk_feedback_to_archive(*args, event_path, resume_from=None, pause=None,
                                    pause_context=None, **kwargs):
    """Publish streamed events only after the complete replay has been verified.

    ``resume_from`` seeds the archive with the part of the pass that a paused run
    had already published, so the resumed pass commits one record of the whole
    population rather than a second half of it.
    """
    if 'event_sink' in kwargs:
        raise ValueError('Event archive owns the event sink')
    with EventArchive(event_path, resume_from=resume_from) as archive:
        result = replay_bulk_feedback(*args, event_sink=archive.write_batch,
                                      archive=archive, pause=pause,
                                      pause_context=pause_context, **kwargs)
        archive.commit()
        result['event_sha256'] = archive.sha256
    return result


def replay_verified_feedback_to_archive(metadata, stimulus, rate_table, *, schedule,
                                        schedule_sha256, morphology_sha256, event_path,
                                        metadata_factory, narrow_cache_directory=None,
                                        resume=None, pause=None, pause_context=None,
                                        **options):
    """Replay a verified fixed schedule and atomically archive selected outputs.

    The caller supplies independently trusted schedule and morphology digests.
    This performs one replay, not recurrent convergence or biological validation.
    """
    from .endpoint_policy import relocate_endpoints
    from .fixed_inputs import fixed_input_digest, fixed_input_factory

    if (not isinstance(metadata, dict) or not callable(metadata_factory)
            or 'events_by_target' in options or 'event_sink' in options):
        raise ValueError('Invalid verified feedback replay inputs')
    graph_sha256 = metadata.get('graph_sha256')
    # Authenticate the schedule exactly as the caller produced it, then apply the
    # deterministic endpoint relocation the GPU grid requires: a finite segment
    # cannot carry a point at a zero-area SWC endpoint. What was moved is returned
    # as endpoint_relocation; nothing is inferred from the solver.
    if fixed_input_digest(schedule) != schedule_sha256:
        raise ValueError('Fixed input schedule digest mismatch')
    relocated = relocate_endpoints(schedule, options.pop('endpoint_grids', None))
    event_factory = fixed_input_factory(relocated['schedule'], options.get('expected_ids'),
        morphology_sha256, graph_sha256=graph_sha256,
        expected_schedule_sha256=relocated['sha256'])
    frozen_hashes = morphology_sha256.copy()

    def checked_metadata(cells):
        if any(cell.get('morphology_sha256') != frozen_hashes.get(cell.get('id'))
               for cell in cells):
            raise ValueError('Verified feedback morphology digest mismatch')
        return metadata_factory(cells)

    narrowed = None
    if narrow_cache_directory is not None:
        from .narrow_geometry import open_narrowed_cells

        # One entry serves every pass of the experiment: decoding a chunk and
        # reducing its tree cannot depend on the schedule being replayed.
        narrowed = open_narrowed_cells(metadata, options['params'],
            directory=narrow_cache_directory, recording=True,
            events=True, reroot=bool(options.get('reroot', False)))
    try:
        result = replay_bulk_feedback_to_archive(metadata, stimulus, rate_table,
            event_path=event_path, events_by_target=event_factory,
            metadata_factory=checked_metadata, narrow_cache=narrowed,
            resume_from=None if resume is None else resume['archive_path'],
            resume=resume, pause=pause, pause_context=pause_context, **options)
    except BaseException:
        if narrowed is not None:
            narrowed.abort()
        raise
    finally:
        if narrowed is not None:
            narrowed.close()
    result['fixed_input_schedule_sha256'] = schedule_sha256
    result['fixed_input_graph_sha256'] = graph_sha256
    result['endpoint_relocation'] = relocated['audit']
    return result
