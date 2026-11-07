import random

import pytest

from service.infrastructure.stimulation.segment_bounds import boxes_match, segment_boxes
from service.infrastructure.stimulation.spatial_candidates import closest_swc_segment


def test_conservative_filter_matches_exact_for_random_queries():
    rng = random.Random(6901)
    lines = ["1 1 0 0 0 1 -1"]
    for node in range(2, 202):
        point = [rng.randrange(-20000, 20000) for _ in range(3)]
        lines.append(f"{node} 1 {' '.join(map(str, point))} 1 {rng.randrange(1, node)}")
    lines.append("202 1 30000 30000 30000 1 -1")
    swc = "\n".join(lines)
    boxes = segment_boxes(swc, max_edges=12)
    for _ in range(200):
        contacts = [[rng.uniform(-250, 250) for _ in range(3)] for _ in range(2)]
        radius = rng.uniform(0, 50)
        exact = closest_swc_segment(swc, contacts)["distance_um"] <= radius
        assert not exact or boxes_match(boxes, contacts, radius)


def test_handles_long_cross_bin_edge_and_isolated_root():
    swc = "1 1 -20000 0 0 1 -1\n2 1 20000 0 0 1 1\n3 1 0 1000 0 1 -1\n"
    boxes = segment_boxes(swc)
    assert boxes_match(boxes, [[0, 0, 0], [500, 0, 0]], 0)
    assert boxes_match(boxes, [[0, 8, 0], [500, 0, 0]], 0)
    assert not boxes_match(boxes, [[0, 20, 0], [500, 0, 0]], 0)


@pytest.mark.parametrize("swc", ["", "1 1 0 0 0 1 2", "1 1 nan 0 0 1 -1", "1 1 0 0 0 1 1"])
def test_invalid_source_is_rejected(swc):
    with pytest.raises(ValueError):
        segment_boxes(swc)
