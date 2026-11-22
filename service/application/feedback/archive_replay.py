"""One experimental population replay driven by authenticated source archives."""

import copy
import os
import shutil
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
                             include_control_crossings=False, _feedback_gate=None,
                             allow_partial_source_geometry=False, events_only=False,
                             active_replay=None, narrow_cache_directory=None,
                             recording_cache_directory=None,
                             pause=None, pause_context=None, resume=None):
    """Build a candidate schedule and replay it once; this is not a converged network.

    The caller authenticates the graph, paired-run configurations and all
    diagnostics. Result files and callbacks must not be exposed before the
    complete replay succeeds.
    """
    if (not isinstance(metadata, dict) or not isinstance(replay_options, dict)
            or type(allow_partial_source_geometry) is not bool
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
        allow_partial_source_geometry=allow_partial_source_geometry,
        events_only=events_only,
        **({'include_control_crossings': True} if include_control_crossings else {}))
    feedback_sha256 = built['schedule_sha256']
    if _feedback_gate is not None:
        _feedback_gate(feedback_sha256)
    # A schedule with no feedback events cannot change the archive: the merged
    # replay would be the baseline replay that produced the incoming archive, and
    # that replay is deterministic, so its output is the input byte for byte.
    # Replaying anyway cost a whole population pass per iteration for nothing,
    # and the current stimulus crosses no threshold at all, so every iteration of
    # a real run took this branch.
    if built['schedule'].get('event_count') == 0 and active_replay is not None:
        return {'replay': active_replay, 'empty_feedback': True,
                'input_schedule_sha256': feedback_sha256,
                'feedback_schedule_sha256': feedback_sha256,
                'baseline_schedule_sha256': baseline_sha256,
                'active_archive_sha256': active_sha256,
                'control_archive_sha256': control_sha256,
                'interpretation': 'empty feedback schedule; the archive is unchanged'}
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
        metadata_factory=metadata_factory, narrow_cache_directory=narrow_cache_directory,
        recording_cache_directory=recording_cache_directory,
        pause=pause, pause_context=pause_context, resume=resume, **replay_options)
    return {'replay': replay, 'input_schedule_sha256': built['schedule_sha256'],
            'feedback_schedule_sha256': feedback_sha256,
            'baseline_schedule_sha256': baseline_sha256,
            'active_archive_sha256': active_sha256, 'control_archive_sha256': control_sha256,
            'interpretation': 'one experimental replay; no network convergence or validation'}


def iterate_archived_feedback(metadata, stimulus, rate_table, *, active_path, active_sha256,
                              control_path, control_sha256, output_event_path, max_iterations,
                              iteration_progress=None, initial_replay=None,
                              pause=None, pause_context=None, resume=None, pause_phase=None,
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
    # The replay that produced the incoming archive: a feedback schedule with no
    # events leaves that archive unchanged, and its receipt is the converged one.
    if initial_replay is not None and not isinstance(initial_replay, dict):
        raise ValueError('Invalid initial archive replay receipt')
    if pause is not None and not callable(getattr(pause, 'check', None)):
        raise ValueError('Invalid archive replay pause controller')
    if (pause is not None) != (pause_context is not None):
        raise ValueError('Archive replay pause requires its context')
    if resume is not None:
        # A checkpoint names the iteration it interrupted and the archives that
        # iteration reads, so resuming rebuilds the same schedule rather than a
        # schedule for a population that happens to start at the same cell.
        required = {'iteration', 'done_ids', 'batches', 'signal', 'archive_path',
                    'history', 'previous', 'receipts', 'archives'}
        if (not isinstance(resume, dict) or not required <= set(resume)
                or type(resume['iteration']) is not int or resume['iteration'] < 1
                or not isinstance(resume['archives'], dict)
                or 'input' not in resume['archives']
                or not Path(resume['archives']['input']['path']).is_file()):
            raise ValueError('Invalid archived feedback resume state')
    previous, seen, history = None, set(), []
    last_result = None if initial_replay is None else {'replay': initial_replay}
    receipts = {} if initial_replay is None else {'initial': initial_replay}
    start, pending = 1, None
    if resume is not None:
        start = resume['iteration']
        history = [signature for signature in resume['history']]
        previous = resume['previous']
        seen = set(history)
        receipts.update(resume['receipts'])
        prior = receipts.get(f'iteration-{start - 1}') or receipts.get('initial')
        last_result = None if prior is None else {'replay': prior}
        pending = resume
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
        if pending is not None:
            # A resumed iteration replays into the archive the checkpoint carried,
            # so the pass continues one archive instead of starting a second one.
            current_path = Path(pending['archives']['input']['path'])
            current_sha = pending['archives']['input']['sha256']
        for number in range(start, max_iterations + 2):
            candidate = Path(scratch) / f'iteration-{number}.jsonl'
            current_options = options.copy()
            if pending is not None and number == start:
                # Replay only what the paused iteration had left, into the archive
                # it had already started: the resumed pass produces the same
                # record as an uninterrupted one, batch boundaries included.
                current_options['resume'] = pending
                pending = None
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
                    _feedback_gate=gate,
                    active_replay=None if last_result is None else last_result['replay'],
                    pause=pause,
                    pause_context=(None if pause is None else {
                        'phase': pause_phase,
                        'iteration': number,
                        'history': history, 'previous': previous,
                        'archives': {'input': {'path': current_path,
                                               'sha256': current_sha},
                                     'output': {'path': candidate,
                                                'sha256': None}},
                        'receipts': receipts}),
                    **current_options)
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
            if result.get('empty_feedback'):
                # No feedback event exists, so the schedule is a fixed point by
                # construction and the archive already holds the outcome. Copy
                # rather than move: this path can be reached on the first
                # iteration, where current_path is the caller's input archive.
                if Path(current_path).resolve() == Path(active_path).resolve():
                    shutil.copyfile(current_path, destination)
                else:
                    os.replace(current_path, destination)
                # Iterations counts replays performed, and the caller's initial
                # replay is the first of them, so an empty schedule converges on
                # this iteration without any further pass.
                return {'status': 'converged', 'iterations': number, 'history': [signature],
                        'replay': result['replay'], 'feedback_schedule_sha256': signature,
                        'empty_feedback': True,
                        'interpretation': 'experimental schedule convergence; '
                                          'not biological validation'}
            history.append(signature)
            previous = signature
            seen.add(signature)
            last_result = result
            # Named by iteration so a checkpoint taken later can say which replay
            # produced the archive it is continuing, and resume with that receipt
            # instead of inferring it from the schedule alone.
            receipts[f'iteration-{number}'] = result['replay']
            current_path, current_sha = candidate, result['replay']['event_sha256']
        raise RuntimeError('Feedback iteration ended unexpectedly')