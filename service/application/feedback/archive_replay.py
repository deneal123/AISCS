"""One experimental population replay driven by authenticated source archives."""

import copy
import os
import tempfile
from pathlib import Path

from .population_bulk_replay import replay_verified_feedback_to_archive
from .schedule import build_feedback_schedule_from_archives


def replay_archived_feedback(metadata, stimulus, rate_table, *, graph, source_ids, index,
                             directories, synapse_parameters, active_path, active_sha256,
                             control_path, control_sha256, diagnostics_factory,
                             morphology_sha256, duration_ms, max_events,
                             max_source_distance_um, max_target_distance_um, output_event_path,
                             metadata_factory, replay_options, target_provider=None,
                             pair_cache=None, baseline_schedule=None, baseline_sha256=None,
                             include_control_crossings=False, _feedback_gate=None):
    """Build a candidate schedule and replay it once; this is not a converged network.

    The caller authenticates the graph, paired-run configurations and all
    diagnostics. Result files and callbacks must not be exposed before the
    complete replay succeeds.
    """
    if (not isinstance(metadata, dict) or not isinstance(replay_options, dict)
            or (_feedback_gate is not None and not callable(_feedback_gate))
            or replay_options.get('expected_ids') != source_ids
            or replay_options.get('duration_ms') != duration_ms
            or metadata.get('graph_sha256') != graph.provenance.get('manifest_sha256')):
        raise ValueError('Archived feedback replay identity mismatch')
    if Path(output_event_path).resolve() in {Path(active_path).resolve(),
                                             Path(control_path).resolve()}:
        raise ValueError('Replay output must not overwrite an input archive')
    built = build_feedback_schedule_from_archives(graph, source_ids, index, directories,
        synapse_parameters, active_path=active_path, active_sha256=active_sha256,
        control_path=control_path, control_sha256=control_sha256,
        diagnostics_factory=diagnostics_factory, morphology_sha256=morphology_sha256,
        duration_ms=duration_ms, max_events=max_events,
        max_source_distance_um=max_source_distance_um,
        max_target_distance_um=max_target_distance_um,
        target_provider=target_provider, pair_cache=pair_cache,
        check_cancelled=replay_options.get('check_cancelled'),
        **({'include_control_crossings': True} if include_control_crossings else {}))
    feedback_sha256 = built['schedule_sha256']
    if _feedback_gate is not None:
        _feedback_gate(feedback_sha256)
    if (baseline_schedule is None) != (baseline_sha256 is None):
        raise ValueError('Baseline schedule and digest must be supplied together')
    if baseline_schedule is not None:
        from .fixed_inputs import fixed_input_digest, merge_fixed_input_schedules

        merged = merge_fixed_input_schedules([(baseline_schedule, baseline_sha256),
            (built['schedule'], feedback_sha256)], source_ids, morphology_sha256,
            graph_sha256=metadata['graph_sha256'], max_events=max_events)
        built['schedule'] = merged
        built['schedule_sha256'] = fixed_input_digest(merged)
    replay = replay_verified_feedback_to_archive(metadata, stimulus, rate_table,
        schedule=built['schedule'], schedule_sha256=built['schedule_sha256'],
        morphology_sha256=morphology_sha256, event_path=output_event_path,
        metadata_factory=metadata_factory, **replay_options)
    return {'replay': replay, 'input_schedule_sha256': built['schedule_sha256'],
            'feedback_schedule_sha256': feedback_sha256,
            'baseline_schedule_sha256': baseline_sha256,
            'active_archive_sha256': active_sha256, 'control_archive_sha256': control_sha256,
            'interpretation': 'one experimental replay; no network convergence or validation'}


def iterate_archived_feedback(metadata, stimulus, rate_table, *, active_path, active_sha256,
                              control_path, control_sha256, output_event_path, max_iterations,
                              iteration_progress=None,
                              **options):
    """Replay until feedback schedules agree; publish only the converged archive.

    The caller authenticates control and baseline identities. A repeated
    non-adjacent schedule is reported as a cycle, not as convergence.
    """
    if type(max_iterations) is not int or not 1 <= max_iterations <= 100:
        raise ValueError('Invalid archived feedback iteration limit')
    if iteration_progress is not None and not callable(iteration_progress):
        raise ValueError('Invalid iteration progress callback')
    destination = Path(output_event_path)
    if destination.resolve() in {Path(active_path).resolve(), Path(control_path).resolve()}:
        raise ValueError('Iteration output must not overwrite an input archive')
    if options.get('baseline_schedule') is not None:
        options['baseline_schedule'] = copy.deepcopy(options['baseline_schedule'])
    previous, seen, history, last_result = None, set(), [], None
    class StopIterationReplay(Exception):
        pass

    class IterationLimitReplay(Exception):
        pass

    def gate(signature):
        if signature == previous or signature in seen:
            raise StopIterationReplay(signature)
        if number > max_iterations:
            raise IterationLimitReplay(signature)

    with tempfile.TemporaryDirectory(dir=destination.parent) as scratch:
        current_path, current_sha = Path(active_path), active_sha256
        for number in range(1, max_iterations + 2):
            candidate = Path(scratch) / f'iteration-{number}.jsonl'
            current_options = options.copy()
            if iteration_progress is not None:
                if number <= max_iterations:
                    iteration_progress(number, 0, len(options['replay_options']['expected_ids']))
                current_options['replay_options'] = {**options['replay_options'],
                    'batch_progress': lambda done, total, current=number:
                        iteration_progress(current, done, total)}
            try:
                result = replay_archived_feedback(metadata, stimulus, rate_table,
                    active_path=current_path, active_sha256=current_sha, control_path=control_path,
                    control_sha256=control_sha256, output_event_path=candidate,
                    _feedback_gate=gate, **current_options)
            except StopIterationReplay as stop:
                signature = stop.args[0]
                history.append(signature)
                if signature == previous:
                    os.replace(current_path, destination)
                    return {'status': 'converged', 'iterations': number - 1, 'history': history,
                            'replay': last_result['replay'], 'feedback_schedule_sha256': signature,
                            'interpretation': 'experimental schedule convergence; '
                                              'not biological validation'}
                return {'status': 'cycle_detected', 'iterations': number - 1, 'history': history}
            except IterationLimitReplay as stop:
                history.append(stop.args[0])
                return {'status': 'iteration_limit', 'iterations': max_iterations,
                        'history': history}
            signature = result['feedback_schedule_sha256']
            history.append(signature)
            previous = signature
            seen.add(signature)
            last_result = result
            current_path, current_sha = candidate, result['replay']['event_sha256']
        raise RuntimeError('Feedback iteration ended unexpectedly')
