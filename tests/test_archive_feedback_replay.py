from types import SimpleNamespace

import pytest

from service.application.feedback.archive_replay import (
    iterate_archived_feedback,
    replay_archived_feedback,
)


def test_archive_replay_uses_built_schedule_and_preserves_input_files(tmp_path, monkeypatch):
    from service.application.feedback import archive_replay

    graph = SimpleNamespace(provenance={'manifest_sha256': 'a' * 64})
    active, control, output = (tmp_path / name for name in ('a', 'c', 'o'))
    active.write_text('active')
    control.write_text('control')
    expected = {'schedule': {'candidate': True}, 'schedule_sha256': 'd' * 64}
    monkeypatch.setattr(archive_replay, 'build_feedback_schedule_from_archives',
                        lambda *args, **kwargs: expected)
    seen = []
    def replay(*args, **kwargs):
        seen.append(kwargs)
        return {'event_sha256': 'e' * 64}
    monkeypatch.setattr(archive_replay, 'replay_verified_feedback_to_archive', replay)
    kwargs = dict(graph=graph, source_ids=[10], index=None, directories=[],
        synapse_parameters={}, active_path=active, active_sha256='b' * 64,
        control_path=control, control_sha256='c' * 64, diagnostics_factory=lambda ids: {},
        morphology_sha256={10: 'f' * 64}, duration_ms=10, max_events=1,
        max_source_distance_um=2, max_target_distance_um=2, output_event_path=output,
        metadata_factory=lambda cells: {}, replay_options={'expected_ids': [10], 'duration_ms': 10})
    result = replay_archived_feedback({'graph_sha256': 'a' * 64}, [], None, **kwargs)
    assert seen[0]['schedule'] == expected['schedule']
    assert seen[0]['schedule_sha256'] == result['input_schedule_sha256'] == 'd' * 64
    assert active.read_text() == 'active' and control.read_text() == 'control'
    with pytest.raises(ValueError, match='overwrite'):
        replay_archived_feedback({'graph_sha256': 'a' * 64}, [], None,
                                 **{**kwargs, 'output_event_path': active})
    with pytest.raises(ValueError, match='identity mismatch'):
        replay_archived_feedback({'graph_sha256': '0' * 64}, [], None, **kwargs)


def test_archive_replay_merges_authenticated_baseline(tmp_path, monkeypatch):
    from service.application.feedback import archive_replay
    from service.application.feedback.fixed_inputs import fixed_input_digest
    from tests.test_fixed_feedback_inputs import fixture

    schedule, hashes = fixture()
    schedule['outside_window'] = 0
    digest = fixed_input_digest(schedule)
    monkeypatch.setattr(archive_replay, 'build_feedback_schedule_from_archives',
                        lambda *args, **kwargs: {'schedule': schedule, 'schedule_sha256': digest})
    observed = []
    def replay(*args, **kwargs):
        observed.append(kwargs['schedule'])
        return {'cells': 2}
    monkeypatch.setattr(archive_replay, 'replay_verified_feedback_to_archive', replay)
    result = replay_archived_feedback({'graph_sha256': 'a' * 64}, [], None,
        graph=SimpleNamespace(provenance={'manifest_sha256': 'a' * 64}), source_ids=[10, 20],
        index=None, directories=[], synapse_parameters={}, active_path=tmp_path / 'a',
        active_sha256='b' * 64, control_path=tmp_path / 'c', control_sha256='c' * 64,
        diagnostics_factory=lambda ids: {}, morphology_sha256=hashes, duration_ms=10,
        max_events=2, max_source_distance_um=2, max_target_distance_um=2,
        output_event_path=tmp_path / 'o', metadata_factory=lambda cells: {},
        replay_options={'expected_ids': [10, 20], 'duration_ms': 10},
        baseline_schedule=schedule, baseline_sha256=digest)
    assert observed[0]['event_count'] == 2
    assert result['baseline_schedule_sha256'] == result['feedback_schedule_sha256'] == digest


@pytest.mark.parametrize('signatures,limit,status', [(['a', 'a'], 1, 'converged'),
    (['a', 'b', 'a'], 2, 'cycle_detected'), (['a', 'b', 'c'], 2, 'iteration_limit')])
def test_iterations_publish_only_converged_archive(tmp_path, monkeypatch, signatures, limit,
                                                   status):
    from service.application.feedback import archive_replay

    destination = tmp_path / 'output'
    destination.write_text('previous')
    values = iter(signatures)
    def replay(*args, output_event_path, **kwargs):
        value = next(values)
        kwargs['_feedback_gate'](value)
        output_event_path.write_text(value)
        return {'feedback_schedule_sha256': value, 'replay': {'event_sha256': value}}
    monkeypatch.setattr(archive_replay, 'replay_archived_feedback', replay)
    result = iterate_archived_feedback({}, [], None, active_path=tmp_path / 'active',
        active_sha256='a', control_path=tmp_path / 'control', control_sha256='c',
        output_event_path=destination, max_iterations=limit)
    assert result['status'] == status
    assert destination.read_text() == ('a' if status == 'converged' else 'previous')
    assert list(tmp_path.iterdir()) == [destination]


def test_iteration_failure_preserves_previous_output_and_removes_scratch(tmp_path, monkeypatch):
    from service.application.feedback import archive_replay

    destination = tmp_path / 'output'
    destination.write_text('previous')
    calls = []
    def replay(*args, output_event_path, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            kwargs['_feedback_gate']('a')
            output_event_path.write_text('intermediate')
            return {'feedback_schedule_sha256': 'a', 'replay': {'event_sha256': 'a'}}
        raise RuntimeError('GPU failure')
    monkeypatch.setattr(archive_replay, 'replay_archived_feedback', replay)
    with pytest.raises(RuntimeError, match='GPU failure'):
        iterate_archived_feedback({}, [], None, active_path=tmp_path / 'active',
            active_sha256='a', control_path=tmp_path / 'control', control_sha256='c',
            output_event_path=destination, max_iterations=3)
    assert destination.read_text() == 'previous'
    assert list(tmp_path.iterdir()) == [destination]
