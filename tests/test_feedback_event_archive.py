import hashlib
import json

import pytest

from service.application.feedback.direct_events import (
    iter_direct_feedback,
    iter_verified_source_feedback,
)
from service.application.feedback.event_archive import (
    EventArchive,
    iter_aligned_archive_batches,
    iter_archived_edge_batches,
    iter_archived_source_batches,
)
from service.application.feedback.outputs import merge_archived_source_events
from service.application.feedback.population_bulk_replay import replay_bulk_feedback_to_archive
from tests.test_direct_feedback import graph


def test_archive_publishes_only_after_verified_replay(tmp_path, monkeypatch):
    destination = tmp_path / 'events.jsonl'
    destination.write_text('previous\n', encoding='utf-8')

    def success(*args, event_sink, **kwargs):
        event_sink({10: {'edge_events': [{'target_id': 20}]}})
        assert destination.read_text(encoding='utf-8') == 'previous\n'
        return {'cells': 1}

    monkeypatch.setattr('service.application.feedback.population_bulk_replay.replay_bulk_feedback',
                        success)
    result = replay_bulk_feedback_to_archive(event_path=destination)
    expected_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
    assert result == {'cells': 1, 'event_sha256': expected_hash}
    assert json.loads(destination.read_text(encoding='utf-8')) == {
        '10': {'edge_events': [{'target_id': 20}]}}
    assert list(tmp_path.iterdir()) == [destination]


def test_archive_failure_preserves_previous_and_removes_staging(tmp_path, monkeypatch):
    destination = tmp_path / 'events.jsonl'
    destination.write_text('previous\n', encoding='utf-8')

    def failure(*args, event_sink, **kwargs):
        event_sink({10: {'edge_events': []}})
        raise ValueError('bad solver receipt')

    monkeypatch.setattr('service.application.feedback.population_bulk_replay.replay_bulk_feedback',
                        failure)
    with pytest.raises(ValueError, match='bad solver receipt'):
        replay_bulk_feedback_to_archive(event_path=destination)
    assert destination.read_text(encoding='utf-8') == 'previous\n'
    assert list(tmp_path.iterdir()) == [destination]


def test_archive_rejects_nonfinite_and_cleans_up(tmp_path):
    destination = tmp_path / 'events.jsonl'
    with pytest.raises(ValueError), EventArchive(destination) as archive:
        archive.write_batch({10: {'value': float('nan')}})
    assert list(tmp_path.iterdir()) == []


def test_archive_stream_routes_verified_cells_and_detects_tampering(tmp_path):
    path = tmp_path / 'events.jsonl'
    event = {'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 2}
    with EventArchive(path) as archive:
        archive.write_batch({10: {'edge_events': [event], 'candidates': []}})
        archive.write_batch({20: {'edge_events': [], 'candidates': []}})
        archive.commit()
        digest = archive.sha256
    stream = iter_archived_edge_batches(path, digest)
    events = list(iter_direct_feedback(graph(), [10, 20], stream, duration_ms=5))
    assert events[0][0]['delivery_tick_ms'] == 3
    assert events[1] == []
    with path.open('ab') as stream:
        stream.write(b'{}\n')
    with pytest.raises(ValueError):
        list(iter_archived_edge_batches(path, digest))


def test_archive_detects_duplicate_keys_and_wrong_digest(tmp_path):
    path = tmp_path / 'events.jsonl'
    path.write_text('{"10":{"edge_events":[]},"10":{"edge_events":[]}}\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Duplicate'):
        list(iter_archived_edge_batches(path, hashlib.sha256(path.read_bytes()).hexdigest()))
    path.write_text('{"10":{"edge_events":[]}}\n', encoding='utf-8')
    with pytest.raises(ValueError, match='digest mismatch'):
        list(iter_archived_edge_batches(path, '0' * 64))


def test_source_archive_preserves_active_synapse_coordinates(tmp_path):
    path = tmp_path / 'events.jsonl'
    candidate = {'source_position_8nm': [1, 2, 3], 'partner_id': '20',
                 'stimulated_ticks_ms': [1]}
    with EventArchive(path) as archive:
        archive.write_batch({10: {'edge_events': [], 'candidates': [candidate]}})
        archive.commit()
        digest = archive.sha256
    sources = list(iter_archived_source_batches(path, digest))
    assert sources[0][10]['candidates'] == [candidate]
    assert list(iter_archived_edge_batches(path, digest)) == [{10: []}]
    with pytest.raises(ValueError, match='digest mismatch'):
        list(iter_archived_source_batches(path, '0' * 64))


def test_align_archives_with_different_batch_orders_and_cleanup(tmp_path):
    active, control = tmp_path / 'a', tmp_path / 'c'
    digests = []
    for path, batches in [(active, [[10, 20], [30]]), (control, [[30], [20, 10]])]:
        with EventArchive(path) as archive:
            for batch in batches:
                archive.write_batch({body: {'edge_events': [], 'candidates': []} for body in batch})
            archive.commit()
            digests.append(archive.sha256)
    result = list(iter_aligned_archive_batches(active, digests[0], control, digests[1],
                                               temporary_directory=tmp_path))
    assert [list(active_batch) for active_batch, _ in result] == [[10, 20], [30]]
    assert [list(control_batch) for _, control_batch in result] == [[10, 20], [30]]
    assert set(tmp_path.iterdir()) == {active, control}
    with pytest.raises(ValueError, match='digest mismatch'):
        list(iter_aligned_archive_batches(active, digests[0], control, '0' * 64,
                                          temporary_directory=tmp_path))
    assert set(tmp_path.iterdir()) == {active, control}
    def cancel():
        raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError, match='cancelled'):
        list(iter_aligned_archive_batches(active, digests[0], control, digests[1],
            temporary_directory=tmp_path, check_cancelled=cancel))
    assert set(tmp_path.iterdir()) == {active, control}


def test_merge_source_events_preserves_geometry_and_rejects_missing_or_extra():
    original = {'body_id': '10', 'duration_ms': 5, 'morphology_sha256': 'verified',
        'candidates': [{'included_in_graph': True, 'partner_id': '20',
            'source_position_8nm': [1, 2, 3], 'child_node_id': 7,
            'stimulated_ticks_ms': [], 'stimulated_crossing_intervals': [[0, 1]]}]}
    archived = {'candidates': [{'partner_id': '20', 'source_position_8nm': [1, 2, 3],
                                'stimulated_ticks_ms': [1]}],
                'edge_events': [{'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 1}]}
    merged = merge_archived_source_events(original, archived)
    assert merged['candidates'][0]['stimulated_ticks_ms'] == [1]
    assert merged['candidates'][0]['child_node_id'] == 7
    assert merged['candidates'][0]['control_ticks_ms'] is None
    assert merged['candidates'][0]['status'] == 'timing_or_trace_ambiguous'
    assert 'stimulated_crossing_intervals' not in merged['candidates'][0]
    assert original['candidates'][0]['stimulated_ticks_ms'] == []
    quiet = {'candidates': [{**archived['candidates'][0], 'stimulated_ticks_ms': []}],
             'edge_events': []}
    paired = merge_archived_source_events(original, archived, control=quiet)
    assert paired['candidates'][0]['status'] == 'stimulus_only_crossing'
    assert paired['candidates'][0]['control_ticks_ms'] == []
    with pytest.raises(ValueError, match='Missing archived'):
        merge_archived_source_events(original, {**archived, 'candidates': []})
    with pytest.raises(ValueError, match='do not match'):
        merge_archived_source_events(original, {**archived, 'edge_events': []})


def test_archived_source_batch_routes_with_verified_geometry(tmp_path):
    path = tmp_path / 'events.jsonl'
    hashes = {10: 'b' * 64, 20: 'c' * 64}
    rows = {10: {'body_id': '10', 'graph_sha256': 'a' * 64,
        'morphology_sha256': hashes[10], 'duration_ms': 5,
        'candidates': [{'included_in_graph': True, 'partner_id': '20',
                        'source_position_8nm': [1, 2, 3], 'child_node_id': 7}]},
        20: {'body_id': '20', 'graph_sha256': 'a' * 64,
        'morphology_sha256': hashes[20], 'duration_ms': 5, 'candidates': []}}
    with EventArchive(path) as archive:
        archive.write_batch({10: {'edge_events': [{'source_id': 10, 'target_id': 20,
            'tick': 1, 'count': 1}], 'candidates': [{'partner_id': '20',
            'source_position_8nm': [1, 2, 3], 'stimulated_ticks_ms': [1]}]}})
        archive.write_batch({20: {'edge_events': [], 'candidates': []}})
        archive.commit()
        digest = archive.sha256
    def run():
        return list(iter_verified_source_feedback(graph(), [10, 20],
            iter_archived_source_batches(path, digest), duration_ms=5,
            diagnostics_factory=lambda ids: {body: rows[body] for body in ids},
            morphology_sha256=hashes))
    result = run()
    assert result[0]['events'][0]['delivery_tick_ms'] == 3
    assert result[0]['diagnostics'][10]['candidates'][0]['child_node_id'] == 7
    assert result[0]['diagnostics'][10]['candidates'][0]['control_ticks_ms'] is None
    assert result[1]['events'] == []
    control = [{10: {'edge_events': [], 'candidates': [{'partner_id': '20',
        'source_position_8nm': [1, 2, 3], 'stimulated_ticks_ms': []}]}},
        {20: {'edge_events': [], 'candidates': []}}]
    paired = list(iter_verified_source_feedback(graph(), [10, 20],
        iter_archived_source_batches(path, digest), duration_ms=5,
        diagnostics_factory=lambda ids: {body: rows[body] for body in ids},
        morphology_sha256=hashes, control_source_batches=control))
    assert paired[0]['diagnostics'][10]['candidates'][0]['status'] == 'stimulus_only_crossing'
    with pytest.raises(ValueError, match='Control source batch'):
        list(iter_verified_source_feedback(graph(), [10, 20],
            iter_archived_source_batches(path, digest), duration_ms=5,
            diagnostics_factory=lambda ids: {body: rows[body] for body in ids},
            morphology_sha256=hashes, control_source_batches=control[:1]))
    rows[10]['morphology_sha256'] = 'd' * 64
    with pytest.raises(ValueError, match='identity mismatch'):
        run()


def test_paired_archives_feed_target_geometry_and_schedule(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from service.application.feedback.schedule import (
        build_feedback_schedule_from_archives,
        combine_partial_feedback_schedules,
        population_feedback_schedule,
        schedule_verified_source_batch,
    )
    from service.infrastructure.stimulation.population.pair_mapping import match_fragment_inputs

    source = {'body_id': '10', 'graph_sha256': 'a' * 64, 'simulation_sha256': 'd' * 64,
        'morphology_sha256': 'b' * 64, 'source_md5': 'verified', 'duration_ms': 5,
        'threshold_mv': -20., 'source_pairs': 1, 'graph_pairs': 1, 'candidates': [{
            'included_in_graph': True, 'partner_id': '20', 'source_position_8nm': [1, 2, 3],
            'child_node_id': 7, 'centerline_distance_um': .1, 'status': 'no_crossing',
            'stimulated_ticks_ms': [], 'control_ticks_ms': []}]}
    active = {'edge_events': [{'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 1}],
        'candidates': [{'partner_id': '20', 'source_position_8nm': [1, 2, 3],
                        'stimulated_ticks_ms': [1]}]}
    quiet = {'edge_events': [], 'candidates': [{**active['candidates'][0],
                                                'stimulated_ticks_ms': []}]}
    merged = merge_archived_source_events(source, active, control=quiet)
    pair = {'body_pre': 10, 'body_post': 20, 'x_pre': 1, 'y_pre': 2, 'z_pre': 3,
            'x_post': 4, 'y_post': 5, 'z_post': 6}
    index = SimpleNamespace(query=lambda *_a, **_kw: {'pairs': [pair], 'truncated': False,
        'source_md5': 'verified', 'total': 1, 'returned': 1})
    module = 'service.infrastructure.stimulation.population.pair_mapping.'
    monkeypatch.setattr(module + 'outgoing', lambda *_a: {'next_offset': None,
        'items': [{'target_id': '20', 'synapse_count': 1}]})
    monkeypatch.setattr(module + 'read_skeleton', lambda *_a: {'swc': 'verified',
        'sha256': 'c' * 64, 'body_id': '20'})
    monkeypatch.setattr(module + 'map_fragment_candidates', lambda *_a: {
        'child_node_ids': [9], 'segment_fractions': [.5], 'centerline_distances_um': [.1]})
    mapping = match_fragment_inputs(merged, index, graph(), 20, [],
        max_source_distance_um=2, max_target_distance_um=2, duration_ms=5)
    event = {'source_id': 10, 'target_id': 20, 'kind': 'physical-source-edge',
        'emission_tick_ms': 1, 'delivery_tick_ms': 3, 'synapse_count': 1,
        'predicted_sign': 1, 'within_window': True, 'affects_replay': True}
    schedule = population_feedback_schedule([10, 20], {'graph_sha256': 'a' * 64,
        'delivery_delay_ms': 2, 'events': [event]}, [mapping], {1: {'weight_us': .01,
        'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}}, duration_ms=5, max_events=10)
    assert schedule['event_count'] == 1
    assert schedule['provenance_by_target'][20][0]['source_id'] == 10
    assert schedule['unresolved'] == []
    batched = schedule_verified_source_batch({'diagnostics': {10: merged}, 'events': [event]},
        [10, 20], graph(), index, [], {1: {'weight_us': .01, 'tau1_ms': .2,
        'tau2_ms': 2., 'reversal_mv': 0.}}, duration_ms=5, max_events=10,
        max_source_distance_um=2, max_target_distance_um=2)
    assert batched['events_by_target'] == {20: schedule['events_by_target'][20]}
    assert batched['provenance_by_target'] == {20: schedule['provenance_by_target'][20]}
    assert batched['source_ids'] == schedule['source_ids']
    combined = combine_partial_feedback_schedules([10, 20], 'a' * 64, [batched], max_events=10)
    assert combined == schedule
    from service.application.feedback.fixed_inputs import fixed_input_digest, fixed_input_factory

    provider = fixed_input_factory(combined, [10, 20], {10: 'b' * 64, 20: 'c' * 64},
        graph_sha256='a' * 64, expected_schedule_sha256=fixed_input_digest(combined))
    assert provider((20,))[20] == schedule['events_by_target'][20]
    target = {'body_id': '20', 'graph_sha256': 'a' * 64, 'morphology_sha256': 'c' * 64,
              'duration_ms': 5, 'candidates': []}
    active_path, control_path = tmp_path / 'active.jsonl', tmp_path / 'control.jsonl'
    with EventArchive(active_path) as archive:
        archive.write_batch({10: active})
        archive.write_batch({20: {'edge_events': [], 'candidates': []}})
        archive.commit()
        active_sha = archive.sha256
    with EventArchive(control_path) as archive:
        archive.write_batch({20: {'edge_events': [], 'candidates': []}, 10: quiet})
        archive.commit()
        control_sha = archive.sha256
    built = build_feedback_schedule_from_archives(graph(), [10, 20], index, [],
        {1: {'weight_us': .01, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}},
        active_path=active_path, active_sha256=active_sha, control_path=control_path,
        control_sha256=control_sha, diagnostics_factory=lambda ids: {
            body: {10: source, 20: target}[body] for body in ids},
        morphology_sha256={10: 'b' * 64, 20: 'c' * 64}, duration_ms=5,
        max_events=10, max_source_distance_um=2, max_target_distance_um=2)
    assert built['schedule'] == schedule
    assert built['schedule_sha256'] == fixed_input_digest(schedule)
    duplicated_path = tmp_path / 'duplicated.jsonl'
    with EventArchive(duplicated_path) as archive:
        archive.write_batch({10: active})
        archive.write_batch({10: active, 20: {'edge_events': [], 'candidates': []}})
        archive.commit()
        duplicate_sha = archive.sha256
    with pytest.raises(ValueError, match='Missing or repeated active source'):
        build_feedback_schedule_from_archives(graph(), [10, 20], index, [],
            {1: {'weight_us': .01, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}},
            active_path=duplicated_path, active_sha256=duplicate_sha, control_path=control_path,
            control_sha256=control_sha, diagnostics_factory=lambda ids: {
                body: {10: source, 20: target}[body] for body in ids},
            morphology_sha256={10: 'b' * 64, 20: 'c' * 64}, duration_ms=5,
            max_events=10, max_source_distance_um=2, max_target_distance_um=2)
    monkeypatch.setattr('service.infrastructure.connectome.synapse_morphology.'
        '_nearest_prepared_segments', lambda *_a: {'child_node_ids': [9],
            'segment_fractions': [.5], 'centerline_distances_um': [.1]})
    cached = build_feedback_schedule_from_archives(graph(), [10, 20], index, [],
        {1: {'weight_us': .01, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}},
        active_path=active_path, active_sha256=active_sha, control_path=control_path,
        control_sha256=control_sha, diagnostics_factory=lambda ids: {
            body: {10: source, 20: target}[body] for body in ids},
        morphology_sha256={10: 'b' * 64, 20: 'c' * 64}, duration_ms=5,
        max_events=10, max_source_distance_um=2, max_target_distance_um=2,
        target_provider=lambda body: ({'body_id': str(body), 'sha256': 'c' * 64}, 'geometry'))
    assert cached['schedule'] == built['schedule']
    with pytest.raises(ValueError, match='target morphology digest'):
        build_feedback_schedule_from_archives(graph(), [10, 20], index, [],
            {1: {'weight_us': .01, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}},
            active_path=active_path, active_sha256=active_sha, control_path=control_path,
            control_sha256=control_sha, diagnostics_factory=lambda ids: {
                body: {10: source, 20: target}[body] for body in ids},
            morphology_sha256={10: 'b' * 64, 20: 'c' * 64}, duration_ms=5,
            max_events=10, max_source_distance_um=2, max_target_distance_um=2,
            target_provider=lambda body: ({'body_id': str(body), 'sha256': 'f' * 64}, 'geometry'))
    with pytest.raises(ValueError, match='digest mismatch'):
        build_feedback_schedule_from_archives(graph(), [10, 20], index, [],
            {1: {'weight_us': .01, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}},
            active_path=active_path, active_sha256='0' * 64, control_path=control_path,
            control_sha256=control_sha, diagnostics_factory=lambda ids: {
                body: {10: source, 20: target}[body] for body in ids},
            morphology_sha256={10: 'b' * 64, 20: 'c' * 64}, duration_ms=5,
            max_events=10, max_source_distance_um=2, max_target_distance_um=2)
    with pytest.raises(ValueError, match='event limit'):
        combine_partial_feedback_schedules([10, 20], 'a' * 64, [batched, batched], max_events=1)
    with pytest.raises(ValueError, match='provenance mismatch'):
        combine_partial_feedback_schedules([10, 20], 'a' * 64,
            [{**batched, 'provenance_sha256': '0' * 64}], max_events=10)
