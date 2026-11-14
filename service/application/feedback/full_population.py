"""Experimental full-population feedback orchestration with staged publication."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import numpy as np

from .archive_replay import iterate_archived_feedback
from .population_bulk_replay import replay_verified_feedback_to_archive


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


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
                                      max_source_distance_um, **options):
    """Build source diagnostics once and reuse them across physical replay passes.

    Scratch is removed on completion or failure. Graph, cache, source index and
    configuration identities must already have been authenticated by the caller.
    """
    from service.infrastructure.stimulation.population.source_store import SourceDiagnosticsStore

    parent = Path(output_directory).parent
    if not parent.is_dir() or 'metadata_factory' in options or 'diagnostics_factory' in options:
        raise ValueError('Invalid source geometry replay options')
    with tempfile.TemporaryDirectory(prefix='.feedback-sources-', dir=parent) as scratch:
        with SourceDiagnosticsStore(Path(scratch) / 'sources.sqlite', graph, index,
                threshold_mv=replay_options['threshold_mv'],
                duration_ms=replay_options['duration_ms'],
                simulation_sha256=configuration_sha256,
                max_distance_um=max_source_distance_um,
                morphology_sha256=morphology_sha256) as sources:
            def complete_metadata(cells):
                result = sources.metadata(cells)
                for diagnostic in result['diagnostics'].values():
                    unresolved = [row for row in diagnostic['candidates']
                                  if row.get('included_in_graph') is True
                                  and row.get('status') == 'geometry_unresolved']
                    if unresolved:
                        raise ValueError('Unresolved source geometry prevents complete feedback: '
                            f"cell {diagnostic['body_id']}, {len(unresolved)} of "
                            f"{len(diagnostic['candidates'])} synapses exceed "
                            f'{max_source_distance_um:g} um')
                return result

            return run_full_population_feedback(metadata, stimulus, rate_table,
                graph=graph, index=index, morphology_sha256=morphology_sha256,
                configuration_sha256=configuration_sha256, output_directory=output_directory,
                replay_options=replay_options, max_source_distance_um=max_source_distance_um,
                metadata_factory=complete_metadata, diagnostics_factory=sources.diagnostics,
                **options)


def run_full_population_feedback(metadata, stimulus, rate_table, *, graph, source_ids,
                                 morphology_sha256, baseline_schedule, baseline_sha256,
                                 configuration_sha256, metadata_factory, diagnostics_factory,
                                 index, directories, synapse_parameters, replay_options,
                                 max_iterations, max_events, max_source_distance_um,
                                 max_target_distance_um, output_directory, target_provider=None,
                                 pair_cache=None, configuration=None, export_markers=False,
                                 progress=None):
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
            or (progress is not None and not callable(progress))):
        raise ValueError('Invalid full-population feedback identity or inputs')
    if any(key in replay_options for key in ('schedule', 'schedule_sha256', 'event_path',
                                              'morphology_sha256', 'metadata_factory')):
        raise ValueError('Conflicting full-population replay options')
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

        def initial(values, path, phase):
            options = replay_options.copy()
            if progress is not None:
                progress({'phase': phase, 'done': 0, 'total': len(ids)})
                options['batch_progress'] = lambda done, total: progress(
                    {'phase': phase, 'done': done, 'total': total})
            return replay_verified_feedback_to_archive(metadata, values, rate_table,
                schedule=baseline_schedule, schedule_sha256=baseline_sha256,
                morphology_sha256=morphology_sha256, event_path=path,
                metadata_factory=metadata_factory, **options)

        active = initial(signal, active_path, 'full_active')
        control = initial(np.zeros_like(signal), initial_control_path, 'full_control')
        if (_digest(active_path) != active['event_sha256']
                or _digest(initial_control_path) != control['event_sha256']):
            raise ValueError('Initial population archive digest mismatch')
        control_iteration = iterate_archived_feedback(metadata, np.zeros_like(signal), rate_table,
            graph=graph, source_ids=source_ids, index=index, directories=directories,
            synapse_parameters=synapse_parameters, active_path=initial_control_path,
            active_sha256=control['event_sha256'], control_path=initial_control_path,
            control_sha256=control['event_sha256'], diagnostics_factory=diagnostics_factory,
            morphology_sha256=morphology_sha256, duration_ms=replay_options['duration_ms'],
            max_events=max_events, max_source_distance_um=max_source_distance_um,
            max_target_distance_um=max_target_distance_um, output_event_path=control_path,
            metadata_factory=metadata_factory, replay_options=replay_options,
            target_provider=target_provider, pair_cache=pair_cache,
            baseline_schedule=baseline_schedule, baseline_sha256=baseline_sha256,
            max_iterations=max_iterations, include_control_crossings=True,
            iteration_progress=(None if progress is None else lambda number, done, total:
                progress({'phase': 'full_control_feedback', 'iteration': number,
                          'done': done, 'total': total})))
        if control_iteration['status'] != 'converged':
            return {'status': control_iteration['status'], 'stage': 'control',
                    'iterations': control_iteration['iterations']}
        control = control_iteration['replay']
        if not control_path.is_file() or _digest(control_path) != control['event_sha256']:
            raise ValueError('Converged control archive digest mismatch')
        initial_control_path.unlink()
        iteration = iterate_archived_feedback(metadata, signal, rate_table, graph=graph,
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
            iteration_progress=(None if progress is None else lambda number, done, total:
                progress({'phase': 'full_feedback', 'iteration': number,
                          'done': done, 'total': total})))
        if iteration['status'] != 'converged':
            return {'status': iteration['status'], 'iterations': iteration['iterations']}
        final = iteration['replay']
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
