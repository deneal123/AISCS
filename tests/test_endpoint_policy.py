import pytest

from service.application.feedback.endpoint_policy import (
    admission_bound,
    endpoint_position,
    relocate_endpoints,
    structural_count,
)
from service.application.feedback.fixed_inputs import fixed_input_digest


def fixture():
    events = {10: [{"child_node_id": 7, "position": .5, "time_ms": 1.}]}
    return {"graph_sha256": "a" * 64, "source_ids": [10],
            "events_by_target": events,
            "provenance_by_target": {10: [{"candidate_index": 0}]},
            "target_morphology_sha256": {10: "c" * 64},
            "event_count": 1, "unresolved": []}


def swc(edges):
    """Build SWC text from (id, parent, xyz_8nm) rows; radii are one unit."""
    return "".join(f"{body} 1 {x} {y} {z} 1 {parent}\n"
                   for body, parent, (x, y, z) in edges)


@pytest.mark.parametrize("position,count,expected",
                         [(0, 1, .5), (1, 1, .5), (0, 3, 1 / 6), (1, 3, 5 / 6),
                          (0, 5, .1), (1, 5, .9)])
def test_endpoint_position_is_the_outermost_segment_centre(position, count, expected):
    assert endpoint_position(position, count) == pytest.approx(expected)


@pytest.mark.parametrize("position,count", [(.5, 1), (0, 2), (0, 0), (True, 1), (0, 1.0)])
def test_endpoint_position_rejects_invalid_requests(position, count):
    with pytest.raises(ValueError, match="endpoint relocation request"):
        endpoint_position(position, count)


def test_relocation_leaves_a_schedule_without_endpoints_byte_identical():
    schedule = fixture()
    digest = fixed_input_digest(schedule)
    result = relocate_endpoints(schedule)
    assert result["schedule"] is schedule
    assert result["sha256"] == digest
    assert result["audit"] is None


@pytest.mark.parametrize("position,count,expected",
                         [(0, 1, .5), (1, 1, .5), (0, 3, 1 / 6), (1, 3, 5 / 6)])
def test_relocation_moves_endpoints_and_keeps_interior_contacts(position, count, expected):
    schedule = fixture()
    schedule["events_by_target"][10] = [
        {"child_node_id": 7, "position": position, "time_ms": 1.},
        {"child_node_id": 8, "position": .25, "time_ms": 2.}]
    original = fixed_input_digest(schedule)
    result = relocate_endpoints(schedule, {10: count})
    moved = result["schedule"]["events_by_target"][10]
    assert moved[0]["position"] == pytest.approx(expected)
    assert moved[1] == {"child_node_id": 8, "position": .25, "time_ms": 2.}
    assert result["audit"]["relocated"] == 1
    assert result["audit"]["cells"] == 1
    assert result["audit"]["max_nseg"] == count
    assert result["sha256"] == fixed_input_digest(result["schedule"])
    assert result["sha256"] != original
    # The caller's schedule is not mutated.
    assert schedule["events_by_target"][10][0]["position"] == position


@pytest.mark.parametrize("schedule", [{}, {"events_by_target": []},
                                     {"events_by_target": {10: [None]}}])
def test_relocation_rejects_malformed_schedules(schedule):
    with pytest.raises(ValueError):
        relocate_endpoints(schedule)


@pytest.mark.parametrize("position", [-.1, 1.1, float("nan"), "0", True])
def test_relocation_rejects_invalid_positions(position):
    schedule = fixture()
    schedule["events_by_target"][10][0]["position"] = position
    with pytest.raises(ValueError, match="event position"):
        relocate_endpoints(schedule)


@pytest.mark.parametrize("count", [0, 2, -3, 1.0, True])
def test_relocation_rejects_invalid_grids(count):
    schedule = fixture()
    schedule["events_by_target"][10][0]["position"] = 1.
    with pytest.raises(ValueError, match="target grid"):
        relocate_endpoints(schedule, {10: count})


def test_admission_bound_adds_the_matching_and_relocation_limits():
    assert admission_bound(2., .5) == pytest.approx(2.5)
    with pytest.raises(ValueError, match="admission limits"):
        admission_bound(-1., 0.)


def test_structural_count_keeps_one_segment_when_every_edge_is_short():
    # 1 um edge in 8 nm units (125 units) needs one segment for a 2 um bound.
    assert structural_count(swc([(1, -1, (0, 0, 0)), (2, 1, (125, 0, 0))]),
                            max_shift_um=2., max_nseg=9) == 1


def test_structural_count_subdivides_only_as_far_as_the_bound_requires():
    # A 4 um edge exceeds a 1 um bound at one segment (2 um) but not at three.
    text = swc([(1, -1, (0, 0, 0)), (2, 1, (500, 0, 0))])
    assert structural_count(text, max_shift_um=1., max_nseg=9) == 3
    with pytest.raises(ValueError, match="structural grid limit"):
        structural_count(text, max_shift_um=.5, max_nseg=3)
