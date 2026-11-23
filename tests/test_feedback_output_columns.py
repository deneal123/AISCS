
import numpy as np
import pytest

from service.application.feedback.output_columns import column_output_plan
from service.application.feedback.outputs import feedback_output_plan, feedback_plan_output_ticks
from service.infrastructure.stimulation.population.source_columns import (
    columns_from_mapping, columns_from_payload,
)
from service.infrastructure.stimulation.population.source_store import _decode, _encode


def _mapping(rows, body=10, distance=2.):
    return {'body_id': str(body), 'morphology_sha256': 'b' * 64,
            'graph_sha256': 'a' * 64, 'source_md5': 'd' * 32,
            'max_distance_um': distance, 'threshold_mv': -20., 'duration_ms': 10,
            'candidates': rows}


def _row(partner, index, child, *, point=(1, 2, 3), fraction=.5, distance=.25,
         included=True):
    return {'included_in_graph': included, 'partner_id': partner,
            'source_position_8nm': list(point), 'child_node_id': child,
            'segment_fraction': fraction, 'centerline_distance_um': distance,
            'result_segment_index': index,
            'status': 'timing_or_trace_ambiguous',
            'stimulated_ticks_ms': None, 'control_ticks_ms': None}


def _columns(rows, body=10, distance=2.):
    return columns_from_mapping(_mapping(rows, body=body, distance=distance), distance)


def _plan(columns, ids, provenance, **options):
    return column_output_plan(options.pop('body', 10), ids, provenance, columns,
        threshold_mv=options.pop('threshold_mv', -20.), duration_ms=options.pop('duration_ms', 10),
        include_candidates=options.pop('include_candidates', True),
        include_unresolved_candidates=options.pop('include_unresolved_candidates', True),
        max_source_distance_um=options.pop('max_source_distance_um', 2.))


def test_columns_round_trip_through_the_durable_payload():
    rows = [_row('20', 1, 4), _row('21', 1, 4, point=(4, 5, 6))]
    mapping = _mapping(rows)
    payload = _encode(columns_from_mapping(mapping, 2.))
    restored = columns_from_payload(payload, 2.)
    assert len(restored) == 2
    assert restored.rows() == _decode(payload, 2.)['candidates']
    assert restored.counts(2.) == (2, 0)


def test_column_plan_matches_the_dictionary_walk_field_by_field():
    rows = [_row('20', 1, 5), _row('21', 1, 5, point=(4, 5, 6)),
            _row('22', 2, 6, point=(7, 8, 9)), _row('23', 0, 4), _row('24', 9, 6,
                                                                    included=False)]
    mapping = _mapping(rows)
    provenance = {'body_id': '10', 'morphology_sha256': 'b' * 64}
    ids = np.array([4, 5, 6])
    expected = feedback_output_plan(10, ids, provenance, mapping, threshold_mv=-20.,
                                    duration_ms=10, include_candidates=True,
                                    include_unresolved_candidates=True,
                                    max_source_distance_um=2.)
    actual = _plan(_columns(rows), ids, provenance)
    assert actual['indices'] == expected['indices']
    assert actual['partners'] == expected['partners']
    assert list(actual['rows']) == expected['rows']
    ticks = {index: [3] for index in actual['indices']}
    assert feedback_plan_output_ticks(actual, ticks) == feedback_plan_output_ticks(
        expected, ticks)


def test_column_plan_keeps_unresolved_placeholders_and_their_order():
    rows = [_row('20', 1, 5, distance=3.), _row('21', 2, 6, point=(4, 5, 6))]
    for row in rows[:1]:
        row['status'] = 'geometry_unresolved'
    provenance = {'body_id': '10', 'morphology_sha256': 'b' * 64}
    ids = np.array([4, 5, 6])
    mapping = _mapping(rows)
    expected = feedback_output_plan(10, ids, provenance, mapping, threshold_mv=-20.,
                                    duration_ms=10, include_candidates=True,
                                    include_unresolved_candidates=True,
                                    max_source_distance_um=2.)
    actual = _plan(_columns(rows), ids, provenance, max_source_distance_um=2.)
    assert actual['indices'] == expected['indices']
    assert list(actual['rows']) == expected['rows']


def test_column_plan_rejects_every_input_the_walk_rejects():
    provenance = {'body_id': '10', 'morphology_sha256': 'b' * 64}
    ids = np.array([4])
    with pytest.raises(ValueError, match='Incompatible output diagnostic identity'):
        _plan(_columns([_row('20', 1, 4)]), ids, {'body_id': '11',
              'morphology_sha256': 'b' * 64})
    with pytest.raises(ValueError, match='Invalid verified output compartment'):
        _plan(_columns([_row('20', 7, 4)]), ids, provenance)
    with pytest.raises(ValueError, match='Conflicting duplicate source coordinate'):
        _plan(_columns([_row('20', 0, 4), _row('20', 1, 4)]), np.array([4, 4]),
              provenance)


def test_column_counts_match_the_payload_count():
    rows = [_row('20', 1, 4, distance=3.), _row('21', 1, 4), _row('22', 1, 4,
                                                           included=False)]
    columns = _columns(rows)
    assert columns.counts(2.) == (2, 1)
    assert columns.counts(4.) == (2, 0)


def test_column_plan_matches_the_walk_for_a_remeshed_cell():
    rows = [_row('20', 0, 4, fraction=.1), _row('21', 0, 4, fraction=.9,
                                                    point=(4, 5, 6)),
            _row('22', 0, 5, fraction=.5, point=(7, 8, 9))]
    mapping = _mapping(rows)
    provenance = {'body_id': '10', 'morphology_sha256': 'b' * 64,
                  'configuration': {'nseg_per_edge': 3}}
    ids = np.array([4, 4, 4, 5, 5, 5])
    expected = feedback_output_plan(10, ids, provenance, mapping, threshold_mv=-20.,
                                    duration_ms=10, include_candidates=True,
                                    include_unresolved_candidates=True,
                                    max_source_distance_um=2.)
    actual = _plan(_columns(rows), ids, provenance)
    assert actual['indices'] == expected['indices']
    assert actual['partners'] == expected['partners']
    assert list(actual['rows']) == expected['rows']

def test_a_quiet_candidate_is_reported_as_omitted_not_silently_dropped():
    """The compact archive records a quiet synapse by leaving its row out.

    Dropping those rows during rendering without reporting it made every cell
    claim a complete candidate list while 165 479 of the 166 700 were short,
    and the merge that rebuilds them then rejected the archive as incomplete.
    """
    rows = [_row('20', 1, 5, point=(1, 2, 3)), _row('21', 2, 6, point=(4, 5, 6))]
    provenance = {'body_id': '10', 'morphology_sha256': 'b' * 64}
    plan = _plan(_columns(rows), np.array([4, 5, 6]), provenance)
    crossed = feedback_plan_output_ticks(plan, {1: [3], 2: []})
    assert crossed['omitted_empty_candidates'] is True
    assert [row['source_position_8nm'] for row in crossed['candidates']] == [[1, 2, 3]]
    silent = feedback_plan_output_ticks(plan, {1: [], 2: []})
    assert silent['omitted_empty_candidates'] is True
    assert silent['candidates'] == []