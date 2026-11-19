"""Experimental full-population feedback orchestration with staged publication."""

import hashlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path

import numpy as np

from service.infrastructure.execution.gpu_batch_settings import reported_settings

from .archive_replay import iterate_archived_feedback
from .population_bulk_replay import replay_verified_feedback_to_archive

_log = logging.getLogger(__name__)


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _exclusion_receipt(exclusions):
    """Describe unmapped synapses honestly; they are never replayed as silence."""
    if not exclusions:
        return {'cells': 0, 'synapses': 0, 'affected': []}
    return {'cells': len(exclusions), 'synapses': sum(exclusions.values()),
            'affected': [{'body_id': body, 'synapses': exclusions[body]}
                         for body in sorted(exclusions)]}


def _timeline(time, active, control, stimulus, *, max_bins=400):
    """Keep measured samples and bin extrema; no interpolation or artifact model."""
    edges = np.linspace(0, len(time), min(max_bins, len(time)) + 1, dtype=int)
    selected = set()
    for start, end in zip(edges[:-1], edges[1:], strict=True):
        selected.update((int(start), int(end - 1)))
        for signal in (active, control, stimulus):
            selected.update((int(start + np.argmin(signal[start:end])),
                             int(start + np.argmax(signal[start:end]))))
    indices = np.array(sorted(selected), dtype=int)
    return {'samples': len(time), 'shown_samples': len(indices),
            'time_ms': time[indices].tolist(), 'neural_uv': active[indices].tolist(),
            'control_uv': control[indices].tolist(),
            'stimulus_fraction': stimulus[indices].tolist(),
            'units': {'time_ms': 'ms', 'neural_uv': 'µV', 'control_uv': 'µV'}}


def run_full_population_from_geometry(metadata, stimulus, rate_table, *, graph, index,
                                      morphology_sha256, configuration_sha256,
                                      output_directory, replay_options,
                                      max_source_distance_um,
                                      allow_partial_source_geometry=False, **options):
    """Build source diagnostics once and reuse them across physical replay passes.

    Scratch is removed on completion or failure. Graph, cache, source index and
    configuration identities must already have been authenticated by the caller.
    """
    from service.infrastructure.stimulation.population.source_store import SourceDiagnosticsStore
    from service.settings import (full_replay_cache_directory, source_diagnostics_cache_path,
                                  source_pair_directory)

    parent = Path(output_directory).parent
    if (not parent.is_dir() or 'metadata_factory' in options
            or 'diagnostics_factory' in options
            or type(allow_partial_source_geometry) is not bool):
        raise ValueError('Invalid source geometry replay options')
    cache_path = options.pop('source_cache_path', None) or source_diagnostics_cache_path()
    scratch = None if cache_path is not None else tempfile.TemporaryDirectory(
        prefix='.feedback-sources-', dir=parent)
    try:
        if cache_path is not None:
            database = Path(cache_path)
            database.parent.mkdir(parents=True, exist_ok=True)
        else:
            database = Path(scratch.name) / 'sources.sqlite'
        # A restored pass is only usable when the source diagnostics it references
        # also survive: the coupled iterations read those rows for every cell that
        # produced an event, and a run-local store would have nothing to read.
        if 'replay_cache_directory' not in options:
            options['replay_cache_directory'] = (full_replay_cache_directory()
                                                 if cache_path is not None else None)
        elif options['replay_cache_directory'] is not None and cache_path is None:
            raise ValueError('The full-population replay cache requires a durable '
                             'source diagnostics cache')
        pairs_path = options.pop('source_pair_directory', None) or source_pair_directory()
        pairs = None
        if pairs_path is not None:
            from service.infrastructure.connectome.source_pairs import SourcePairStore

            pairs = SourcePairStore(Path(pairs_path))
        with SourceDiagnosticsStore(database, graph, index, pairs=pairs,
                threshold_mv=replay_options['threshold_mv'],
                duration_ms=replay_options['duration_ms'],
                simulation_sha256=configuration_sha256,
                max_distance_um=max_source_distance_um,
                morphology_sha256=morphology_sha256) as sources:
            # A restored first pass performs no mapping, so it is only usable once
            # the durable database holds every cell; otherwise the coupled
            # iterations have nothing to read for the cells that emitted events.
            if options.get('replay_cache_directory') is not None and not sources.covers():
                _log.info('source diagnostics database is incomplete; replay cache disabled')
                options['replay_cache_directory'] = None

            # Opt-in: a cell whose registered synapses lie outside the source
            # tolerance keeps those synapses explicitly unresolved instead of
            # stopping the population. They are never replayed as silence; the
            # count is published with the result so the exclusion stays visible.
            excluded = {}

            def complete_metadata(cells):
                result = sources.metadata(cells)
                counts = {}
                for diagnostic in result['diagnostics'].values():
                    candidates = diagnostic['candidates']
                    registered = sum(1 for row in candidates
                                     if row.get('included_in_graph') is True)
                    unresolved = sum(1 for row in candidates
                                     if row.get('included_in_graph') is True
                                     and row.get('status') == 'geometry_unresolved')
                    counts[int(diagnostic['body_id'])] = (registered, unresolved)
                    if not unresolved:
                        continue
                    if not allow_partial_source_geometry:
                        raise ValueError('Unresolved source geometry prevents complete feedback: '
                            f"cell {diagnostic['body_id']}, {unresolved} of "
                            f"{len(candidates)} synapses exceed "
                            f'{max_source_distance_um:g} um')
                    excluded[int(diagnostic['body_id'])] = unresolved
                sources.remember_counts(counts)
                return result

            # The receipt must describe the geometry, not the path taken to it:
            # a run restored from the replay cache never maps a cell, so the
            # exclusions are read back from the durable store instead. Only a
            # complete side table is used; a partial one would report a smaller
            # count than the geometry actually holds.
            cached_counts = sources.cached_counts()
            if cached_counts is None and sources.covers():
                cached_counts = sources.fill_counts()
            if cached_counts is not None:
                for body, (_registered, unresolved) in cached_counts.items():
                    if unresolved:
                        if not allow_partial_source_geometry:
                            raise ValueError('Unresolved source geometry prevents complete '
                                f'feedback: cell {body}, {unresolved} synapses exceed '
                                f'{max_source_distance_um:g} um')
                        excluded[body] = unresolved

            return run_full_population_feedback(metadata, stimulus, rate_table,
                graph=graph, index=index, morphology_sha256=morphology_sha256,
                configuration_sha256=configuration_sha256, output_directory=output_directory,
                replay_options=replay_options, max_source_distance_um=max_source_distance_um,
                metadata_factory=complete_metadata, diagnostics_factory=sources.diagnostics,
                source_geometry_exclusions=excluded,
                allow_partial_source_geometry=allow_partial_source_geometry, **options)
    finally:
        if scratch is not None:
            scratch.cleanup()


def run_full_population_feedback(metadata, stimulus, rate_table, *, graph, source_ids,
                                 morphology_sha256, baseline_schedule, baseline_sha256,
                                 configuration_sha256, metadata_factory, diagnostics_factory,
                                 index, directories, synapse_parameters, replay_options,
                                 max_iterations, max_events, max_source_distance_um,
                                 max_target_distance_um, output_directory, target_provider=None,
                                 pair_cache=None, configuration=None, export_markers=False,
                                 replay_cache_directory=None, progress=None,
                                 source_geometry_exclusions=None,
                                 allow_partial_source_geometry=False):
    """Stage paired physical replays and publish only converged experimental results.

    Callers must authenticate the graph, geometry, diagnostics, baseline schedule,
    parameters and their association with the configuration. No claim of
    biological validity or clinical measurement follows from convergence.
    """
    graph_hash = graph.provenance.get('manifest_sha256')
    ids = [int(value) for value in graph.ids]
    signal = np.asarray(stimulus, dtype=float)
    if (not isinstance(metadata, dict) or metadata.get('graph_sha256') != graph_hash
            or not isinstance(graph_hash, str) or not re.fullmatch('[a-f0-9]{64}', graph_hash)
            or not isinstance(configuration_sha256, str)
            or not re.fullmatch('[a-f0-9]{64}', configuration_sha256)
            or not isinstance(source_ids, list) or source_ids != ids or not ids
            or any(type(body) is not int or body <= 0 for body in source_ids)
            or len(set(source_ids)) != len(source_ids)
            or not isinstance(replay_options, dict)
            or replay_options.get('expected_ids') != source_ids
            or not isinstance(morphology_sha256, dict) or set(morphology_sha256) != set(ids)
            or not callable(metadata_factory) or not callable(diagnostics_factory)
            or signal.ndim != 1 or len(signal) < 2 or not np.isfinite(signal).all()
            or type(export_markers) is not bool
            or type(allow_partial_source_geometry) is not bool
            or (source_geometry_exclusions is not None and (
                not isinstance(source_geometry_exclusions, dict)
                or any(type(body) is not int or body <= 0
                       or type(count) is not int or count < 1
                       for body, count in source_geometry_exclusions.items())))
            or (progress is not None and not callable(progress))):
        raise ValueError('Invalid full-population feedback identity or inputs')
    if any(key in replay_options for key in ('schedule', 'schedule_sha256', 'event_path',
                                              'morphology_sha256', 'metadata_factory')):
        raise ValueError('Conflicting full-population replay options')
    if source_geometry_exclusions and not allow_partial_source_geometry:
        raise ValueError('Source geometry exclusions require the partial source geometry policy')
    if configuration is not None:
        try:
            configuration_bytes = json.dumps(configuration, sort_keys=True,
                separators=(',', ':'), allow_nan=False).encode('utf8')
        except (TypeError, ValueError) as exc:
            raise ValueError('Invalid full-population configuration') from exc
        if hashlib.sha256(configuration_bytes).hexdigest() != configuration_sha256:
            raise ValueError('Full-population configuration digest mismatch')
    destination = Path(output_directory)
    if not destination.parent.is_dir() or destination.exists() or destination.is_symlink():
        raise ValueError('Full-population output must be a new directory')
    signal = signal.copy()
    with tempfile.TemporaryDirectory(prefix='.full-population-', dir=destination.parent) as temp:
        staged = Path(temp) / 'result'
        staged.mkdir()
        active_path = staged / 'initial-active.jsonl'
        initial_control_path = staged / '.initial-control.jsonl'
        control_path = staged / 'control.jsonl'
        final_path = staged / 'activity.jsonl'

        cache = None
        if replay_cache_directory is not None:
            from .replay_cache import ReplayPassCache, pass_key

            cache = ReplayPassCache(replay_cache_directory)

        def cache_key(phase, values):
            return pass_key(phase, values, graph_sha256=graph_hash,
                configuration_sha256=configuration_sha256, baseline_sha256=baseline_sha256,
                replay_options={**replay_options,
                                'max_source_distance_um': max_source_distance_um,
                                'allow_partial_source_geometry':
                                    allow_partial_source_geometry})

        def initial(values, path, phase):
            key = None if cache is None else cache_key(phase, values)
            if cache is not None:
                restored = cache.load(key, path)
                if restored is not None:
                    if (restored['cells'] != len(ids)
                            or _digest(path) != restored['event_sha256']):
                        raise ValueError('Cached population archive digest mismatch')
                    _log.info('restored %s from the replay cache (%s)', phase, key[:12])
                    if progress is not None:
                        progress({'phase': phase, 'done': len(ids), 'total': len(ids)})
                    return restored
            options = replay_options.copy()
            if progress is not None:
                progress({'phase': phase, 'done': 0, 'total': len(ids)})
                options['batch_progress'] = lambda done, total: progress(
                    {'phase': phase, 'done': done, 'total': total})
            receipt = replay_verified_feedback_to_archive(metadata, values, rate_table,
                schedule=baseline_schedule, schedule_sha256=baseline_sha256,
                morphology_sha256=morphology_sha256, event_path=path,
                metadata_factory=metadata_factory, **options)
            if cache is not None:
                cache.save(key, path, receipt)
            return receipt

        initial_active = initial(signal, active_path, 'full_active')
        active = initial_active
        zeros = np.zeros_like(signal)

        def control_branch():
            """Replay the paired control branch: the zero stimulus and its own loop.

            Nothing in it depends on the stimulus, so the branch is a function of
            the configuration alone and can be cached as one unit.
            """
            first = initial(zeros, initial_control_path, 'full_control')
            if _digest(initial_control_path) != first['event_sha256']:
                raise ValueError('Initial population archive digest mismatch')
            loop = iterate_archived_feedback(metadata, zeros, rate_table,
                # The zero-stimulus replay that produced the incoming control archive:
                # an empty feedback schedule hands its receipt back as the converged one.
                initial_replay=first,
                graph=graph, source_ids=source_ids, index=index, directories=directories,
                synapse_parameters=synapse_parameters, active_path=initial_control_path,
                active_sha256=first['event_sha256'], control_path=initial_control_path,
                control_sha256=first['event_sha256'], diagnostics_factory=diagnostics_factory,
                morphology_sha256=morphology_sha256, duration_ms=replay_options['duration_ms'],
                max_events=max_events, max_source_distance_um=max_source_distance_um,
                max_target_distance_um=max_target_distance_um, output_event_path=control_path,
                metadata_factory=metadata_factory, replay_options=replay_options,
                target_provider=target_provider, pair_cache=pair_cache,
                baseline_schedule=baseline_schedule, baseline_sha256=baseline_sha256,
                max_iterations=max_iterations, include_control_crossings=True,
                allow_partial_source_geometry=allow_partial_source_geometry,
                # See the coupled iteration below: complete_metadata owns the
                # population-wide unresolved-geometry policy, so mapping only the
                # emitting cells here cannot hide an unresolvable source.
                events_only=True,
                iteration_progress=(None if progress is None else lambda number, done, total:
                    progress({'phase': 'full_control_feedback', 'iteration': number,
                              'done': done, 'total': total})))
            return first, loop

        branch_key = None if cache is None else pass_key('full_control_branch', zeros,
            graph_sha256=graph_hash, configuration_sha256=configuration_sha256,
            baseline_sha256=baseline_sha256,
            replay_options={**replay_options, 'max_source_distance_um': max_source_distance_um,
                            'max_target_distance_um': max_target_distance_um,
                            'max_iterations': max_iterations})
        restored = None if cache is None else cache.load(branch_key, control_path)
        if restored is not None:
            extra = restored.get('extra') or {}
            first, loop = extra.get('initial_control'), extra.get('control_iteration')
            if (restored['cells'] != len(ids) or _digest(control_path) != restored['event_sha256']
                    or not isinstance(first, dict) or not isinstance(loop, dict)
                    or loop.get('status') != 'converged'):
                raise ValueError('Cached control branch receipt is invalid')
            initial_control = dict(first, neural_uv=None)
            control_iteration = dict(loop, replay=restored)
            _log.info('restored the paired control branch from the replay cache (%s)',
                      branch_key[:12])
            if progress is not None:
                progress({'phase': 'full_control', 'done': len(ids), 'total': len(ids)})
                progress({'phase': 'full_control_feedback', 'iteration': loop['iterations'],
                          'done': len(ids), 'total': len(ids)})
        else:
            initial_control, control_iteration = control_branch()
            if cache is not None and control_iteration['status'] == 'converged':
                cache.save(branch_key, control_path, control_iteration['replay'],
                    extra={'initial_control': {
                               key: initial_control[key] for key in ('event_sha256', 'cells',
                                   'solver_kernels', 'endpoint_relocation')},
                           'control_iteration': {
                               key: control_iteration[key] for key in ('status', 'iterations',
                                   'feedback_schedule_sha256')}})
        if control_iteration['status'] != 'converged':
            return {'status': control_iteration['status'], 'stage': 'control',
                    'iterations': control_iteration['iterations']}
        control = control_iteration['replay']
        if not control_path.is_file() or _digest(control_path) != control['event_sha256']:
            raise ValueError('Converged control archive digest mismatch')
        initial_control_path.unlink(missing_ok=True)
        # The coupled branch is closed once both starting archives exist: it is a
        # function of the two digests above and of the configuration, so it can be
        # restored like the stimulus-only passes. Its archive is the published
        # activity record, so the key also names the archives it started from.
        final_key = None if cache is None else pass_key('full_feedback_branch', signal,
            graph_sha256=graph_hash, configuration_sha256=configuration_sha256,
            baseline_sha256=baseline_sha256,
            replay_options={**replay_options, 'max_source_distance_um': max_source_distance_um,
                            'max_target_distance_um': max_target_distance_um,
                            'max_iterations': max_iterations,
                            'active_archive_sha256': active['event_sha256'],
                            'control_archive_sha256': control['event_sha256']})
        restored = None if cache is None else cache.load(final_key, final_path)
        if restored is not None:
            extra = restored.get('extra') or {}
            if (restored['cells'] != len(ids) or _digest(final_path) != restored['event_sha256']
                    or extra.get('status') != 'converged'
                    or not isinstance(extra.get('feedback_schedule_sha256'), str)
                    or not isinstance(extra.get('iterations'), int)):
                raise ValueError('Cached feedback branch receipt is invalid')
            iteration = dict(extra, replay=restored)
            _log.info('restored the coupled feedback branch from the replay cache (%s)',
                      final_key[:12])
            if progress is not None:
                progress({'phase': 'full_feedback', 'iteration': iteration['iterations'],
                          'done': len(ids), 'total': len(ids)})
        else:
            iteration = iterate_archived_feedback(metadata, signal, rate_table, graph=graph,
                # The active replay that produced the incoming archive; with an empty
                # feedback schedule it is also the converged coupled result.
                initial_replay=active,
                source_ids=source_ids, index=index, directories=directories,
                synapse_parameters=synapse_parameters, active_path=active_path,
                active_sha256=active['event_sha256'], control_path=control_path,
                control_sha256=control['event_sha256'], diagnostics_factory=diagnostics_factory,
                morphology_sha256=morphology_sha256, duration_ms=replay_options['duration_ms'],
                max_events=max_events, max_source_distance_um=max_source_distance_um,
                max_target_distance_um=max_target_distance_um, output_event_path=final_path,
                metadata_factory=metadata_factory, replay_options=replay_options,
                target_provider=target_provider, pair_cache=pair_cache,
                baseline_schedule=baseline_schedule, baseline_sha256=baseline_sha256,
                max_iterations=max_iterations, include_control_crossings=True,
                allow_partial_source_geometry=allow_partial_source_geometry,
                # Only cells that actually emitted a crossing are mapped; a quiet
                # cell contributes no schedule entry and its diagnostics would be
                # read, re-verified and merged only to be dropped again.
                events_only=True,
                iteration_progress=(None if progress is None else lambda number, done, total:
                    progress({'phase': 'full_feedback', 'iteration': number,
                              'done': done, 'total': total})))
            if iteration['status'] == 'converged' and cache is not None:
                cache.save(final_key, final_path, iteration['replay'],
                    extra={key: iteration[key] for key in ('status', 'iterations',
                                                           'feedback_schedule_sha256')})
        if iteration['status'] != 'converged':
            return {'status': iteration['status'], 'iterations': iteration['iterations']}
        final = iteration['replay']
        relocation = {'initial_active': initial_active.get('endpoint_relocation'),
                      'initial_control': initial_control.get('endpoint_relocation'),
                      'control': control.get('endpoint_relocation'),
                      'active': final.get('endpoint_relocation')}
        # Record which kernel actually solved the population: every physical
        # batch reports whether the accelerated cell-major path or the generic
        # node-major fallback ran, and the totals go into the published result.
        kernels = {'accelerated_cell_major': 0, 'generic': 0, 'batches': 0}
        for item in (initial_active, initial_control, control, final):
            receipt = item.get('solver_kernels')
            if not isinstance(receipt, dict):
                raise ValueError('Population feedback kernel receipt is missing')
            for key in kernels:
                value = receipt.get(key)
                if type(value) is not int or value < 0:
                    raise ValueError('Population feedback kernel receipt is invalid')
                kernels[key] += value
        if kernels['batches'] < 1 or kernels['accelerated_cell_major'] < 1:
            raise ValueError('Full-population feedback ran without the accelerated '
                             'cell-major kernel')
        batch_settings = reported_settings(replay_options)
        time = np.asarray(replay_options['time_ms'], dtype=float)
        arrays = [np.asarray(item['neural_uv'], dtype=float) for item in (active, control, final)]
        if (time.shape != signal.shape or not np.isfinite(time).all()
                or any(array.shape != time.shape or not np.isfinite(array).all()
                       for array in arrays)
                or any(item.get('cells') != len(ids) for item in (active, control, final))
                or not final_path.is_file() or _digest(final_path) != final['event_sha256']):
            raise ValueError('Incomplete converged population feedback result')
        trace_path = staged / 'signals.npz'
        np.savez_compressed(trace_path, time_ms=time, initial_active_uv=arrays[0],
                            control_uv=arrays[1], converged_active_uv=arrays[2])
        files = {path.name: _digest(path) for path in (active_path, control_path, final_path,
                                                       trace_path)}
        marker_receipt = None
        if export_markers:
            from .population_visualization import export_population_markers

            marker = staged / 'coupled-source-events.bin'
            marker_receipt = export_population_markers(
                marker, final_path, final['event_sha256'], graph,
                duration_ms=replay_options['duration_ms'],
                configuration_sha256=configuration_sha256)
            files[marker.name] = _digest(marker)
        preview = {'kind': 'experimental-full-population-feedback', 'status': 'converged',
            'graph_cells': len(ids), 'source_cells': len(ids),
            'duration_ms': replay_options['duration_ms'], 'iterations': iteration['iterations'],
            'control_iterations': control_iteration['iterations'],
            'candidate_cell_time_markers': (None if marker_receipt is None
                                            else marker_receipt['events']),
            'endpoint_relocation': relocation, 'solver_kernels': kernels,
            'source_geometry_exclusions': _exclusion_receipt(source_geometry_exclusions),
            'timeline': _timeline(time, arrays[2], arrays[1], signal),
            'interpretation': 'segment threshold markers are not whole-cell spikes; '
                              'numerical convergence is not biological validation'}
        preview_path = staged / 'preview.json'
        preview_path.write_text(json.dumps(preview, indent=2, allow_nan=False) + '\n',
                                encoding='utf8')
        files[preview_path.name] = _digest(preview_path)
        manifest = {'kind': 'experimental-full-population-feedback', 'status': 'converged',
                    'graph_sha256': graph_hash, 'configuration_sha256': configuration_sha256,
                    'baseline_schedule_sha256': baseline_sha256,
                    'feedback_schedule_sha256': iteration['feedback_schedule_sha256'],
                    'control_feedback_schedule_sha256':
                        control_iteration['feedback_schedule_sha256'],
                    'cells': len(ids), 'iterations': iteration['iterations'], 'file_hashes': files,
                    'control_iterations': control_iteration['iterations'],
                    'endpoint_relocation': relocation, 'solver_kernels': kernels,
                    'batch_settings': batch_settings,
                    'allow_partial_source_geometry': allow_partial_source_geometry,
                    'source_geometry_exclusions':
                        _exclusion_receipt(source_geometry_exclusions),
                    'interpretation': 'numerical schedule convergence; not biological validation'}
        manifest['files'] = [{'name': name, 'bytes': (staged / name).stat().st_size,
                              'sha256': digest} for name, digest in files.items()]
        if configuration is not None:
            manifest['configuration'] = configuration
        manifest_path = staged / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False) + '\n',
                                 encoding='utf8')
        manifest_hash = _digest(manifest_path)
        os.rename(staged, destination)
    return {'status': 'converged', 'iterations': iteration['iterations'],
            'cells': len(ids), 'manifest_sha256': manifest_hash}