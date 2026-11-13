import pytest

from service.infrastructure.stimulation.experimental_gpu.events import midpoint_events, refined_segment_events


def event(child=10, time=2., position=.5):
    return {'child_node_id': child, 'position': position, 'time_ms': time,
            'weight_us': .001, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}


def test_midpoints_map_and_sort_without_losing_simultaneous_events():
    events = [event(20, 4), event(10, 2), event(20, 2)]
    result = midpoint_events(events, [20, 10], duration_ms=10, nseg_per_edge=1)
    assert [row['segment_index'] for row in result] == [1, 0, 0]
    assert [row['time_ms'] for row in result] == [2, 2, 4]
    assert events[0]['time_ms'] == 4


def test_interior_event_retains_original_position():
    result = midpoint_events([event(position=.3)], [10], duration_ms=10, nseg_per_edge=1)
    assert result[0]['position'] == .3
    assert result[0]['segment_index'] == 0


@pytest.mark.parametrize('bad', [event(position=0), event(position=1), event(child=99), event(time=10),
                                 {**event(), 'tau2_ms': .2}, {**event(), 'weight_us': float('nan')}])
def test_unsupported_events_are_rejected(bad):
    with pytest.raises(ValueError):
        midpoint_events([bad], [10], duration_ms=10, nseg_per_edge=1)


@pytest.mark.parametrize('nseg', [0, 3, True])
def test_multisegment_and_invalid_discretizations_are_rejected(nseg):
    with pytest.raises(ValueError):
        midpoint_events([event()], [10], duration_ms=10, nseg_per_edge=nseg)


def test_refined_grid_uses_actual_solver_order_and_segment_boundaries():
    segments = [(10, 2, 3), (20, 0, 1), (10, 0, 3), (10, 1, 3)]
    rows = refined_segment_events([event(position=.2), event(position=1 / 3),
                                   event(position=.9)], segments, duration_ms=10)
    assert [row['segment_index'] for row in rows] == [2, 3, 0]


@pytest.mark.parametrize('segments', [[(10, 0, 3)], [(10, 0, 2)],
                                      [(10, 0, 1), (10, 0, 1)]])
def test_refined_grid_rejects_incomplete_or_ambiguous_segments(segments):
    with pytest.raises(ValueError):
        refined_segment_events([event()], segments, duration_ms=10)
