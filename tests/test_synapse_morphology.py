import numpy as np
import pytest

from service.infrastructure.connectome.synapse_morphology import (
    merge_candidate_pages,
    nearest_swc_segments,
    prepare_registered_morphology,
    registered_page_candidates,
)

SWC = "1 1 0 0 0 1 -1\n2 3 125 0 0 1 1\n3 3 125 125 0 1 2\n"


def test_nearest_segment_projection_and_endpoint_clamping():
    mapped = nearest_swc_segments(SWC, [[.5, .2, 0], [1.4, .7, 0], [-.2, 0, 0]])
    assert mapped["child_node_ids"] == [2, 3, 2]
    np.testing.assert_allclose(mapped["segment_fractions"], [.5, .7, 0])
    np.testing.assert_allclose(mapped["centerline_distances_um"], [.2, .4, .2])
    np.testing.assert_allclose(mapped["interpolated_swc_radii_um"], [.008, .008, .008])


def test_interpolated_radius_uses_selected_segment_fraction():
    swc = "1 1 0 0 0 10 -1\n2 3 125 0 0 20 1\n"
    mapped = nearest_swc_segments(swc, [[.25, .1, 0]])
    np.testing.assert_allclose(mapped["interpolated_swc_radii_um"], [.1])


def test_ties_use_lowest_child_and_batching_is_deterministic():
    swc = "1 1 0 0 0 1 -1\n3 3 125 0 0 1 1\n2 3 0 125 0 1 1\n"
    points = [[.2, .2, 0], [.3, .3, 0]]
    one = nearest_swc_segments(swc, points, point_batch_size=1)
    many = nearest_swc_segments(swc, points, point_batch_size=2)
    assert one == many
    assert one["child_node_ids"] == [2, 2]


def test_segment_batches_search_beyond_first_block():
    rows = ["1 1 0 0 0 1 -1"]
    rows += [f"{i} 3 {i * 125} 0 0 1 {i-1}" for i in range(2, 2101)]
    result = nearest_swc_segments("\n".join(rows), [[2099.5, .1, 0]])
    assert result["child_node_ids"] == [2100]
    np.testing.assert_allclose(result["centerline_distances_um"], [.1])


def test_random_points_match_independent_scalar_projection():
    rng = np.random.default_rng(734)
    vertices = rng.integers(-1000, 1000, size=(81, 3))
    rows = [f"1 1 {vertices[0, 0]} {vertices[0, 1]} {vertices[0, 2]} 1 -1"]
    for i in range(1, len(vertices)):
        x, y, z = vertices[i]
        rows.append(f"{i + 1} 3 {x} {y} {z} 1 {i}")
    points = rng.normal(size=(45, 3)) * 4
    actual = nearest_swc_segments("\n".join(rows), points, point_batch_size=7)
    for point, child, fraction, distance in zip(
        points, actual["child_node_ids"], actual["segment_fractions"],
        actual["centerline_distances_um"], strict=True,
    ):
        choices = []
        for i in range(1, len(vertices)):
            a, b = vertices[i - 1] * .008, vertices[i] * .008
            step = b - a
            position = max(0., min(1., float(np.dot(point - a, step) / np.dot(step, step))))
            choices.append((float(np.linalg.norm(point - (a + position * step))), i + 1, position))
        minimum = min(row[0] for row in choices)
        expected = min((row for row in choices if np.isclose(
            row[0] ** 2, minimum ** 2, rtol=1e-12, atol=1e-18
        )), key=lambda row: row[1])
        assert child == expected[1]
        assert fraction == pytest.approx(expected[2], abs=1e-12)
        assert distance == pytest.approx(expected[0], abs=1e-12)


def test_invalid_geometry_and_coordinates_are_rejected():
    with pytest.raises(ValueError, match="zero-length"):
        nearest_swc_segments("1 1 0 0 0 1 -1\n2 3 0 0 0 1 1\n", [[0, 0, 0]])
    with pytest.raises(ValueError, match="coordinates"):
        nearest_swc_segments(SWC, [[np.nan, 0, 0]])
    with pytest.raises(ValueError, match="batch"):
        nearest_swc_segments(SWC, [[0, 0, 0]], point_batch_size=True)
    with np.errstate(over="ignore", invalid="ignore"):
        with pytest.raises(ValueError, match="Non-finite"):
            nearest_swc_segments(SWC, [[1e308, 0, 0]])


@pytest.mark.parametrize("direction, expected_partner, expected_child", [
    ("outgoing", "22", 2), ("incoming", "11", 3),
])
def test_registered_page_uses_corresponding_side(monkeypatch, direction, expected_partner,
                                                 expected_child):
    page = {"truncated": False, "counts_match": True, "graph_next_offset": None,
            "source_md5": "source", "graph_manifest_sha256": "graph",
            "coordinate_frame": "8nm", "pairs": [{
                "body_pre": 11, "body_post": 22, "x_pre": 63, "y_pre": 0, "z_pre": 0,
                "x_post": 125, "y_post": 63, "z_post": 0,
            }]}
    monkeypatch.setattr("service.infrastructure.connectome.synapse_index.registered_page_pairs",
                        lambda *args, **kwargs: page)
    monkeypatch.setattr("service.infrastructure.connectome.morphology_repository.read_skeleton",
                        lambda *args: {"body_id": "11", "swc": SWC, "sha256": "skeleton"})
    result = registered_page_candidates(None, None, 11, direction, 0, 20, [])
    assert result["candidates"][0]["partner_id"] == expected_partner
    assert result["candidates"][0]["child_node_id"] == expected_child
    assert result["morphology_sha256"] == "skeleton"
    assert result["source_md5"] == "source"
    selected = registered_page_candidates(None, None, 11, direction, 0, 20, [],
                                          candidate_partner_ids=set())
    assert selected["candidates"] == []
    assert selected["selection"] == "specified partner IDs"
    for failure in ("truncated", "counts_match"):
        broken = {**page, failure: failure == "truncated"}
        monkeypatch.setattr("service.infrastructure.connectome.synapse_index.registered_page_pairs",
                            lambda *args, result=broken, **kwargs: result)
        with pytest.raises(ValueError, match="truncated or inconsistent"):
            registered_page_candidates(None, None, 11, direction, 0, 20, [])


def test_prepared_morphology_produces_identical_pages_without_reloading(monkeypatch):
    page = {"truncated": False, "counts_match": True, "graph_next_offset": None,
            "source_md5": "source", "graph_manifest_sha256": "graph", "coordinate_frame": "8nm",
            "pairs": [{"body_pre": 11, "body_post": 22, "x_post": 125, "y_post": 63,
                       "z_post": 0}]}
    monkeypatch.setattr("service.infrastructure.connectome.synapse_index.registered_page_pairs",
                        lambda *args, **kwargs: page)
    calls = []

    def read(*args):
        calls.append(args)
        return {"body_id": "22", "swc": SWC, "sha256": "skeleton"}

    monkeypatch.setattr("service.infrastructure.connectome.morphology_repository.read_skeleton",
                        read)
    expected = registered_page_candidates(None, None, 22, 'incoming', 0, 20, [])
    prepared = prepare_registered_morphology(22, [])
    for _ in range(3):
        assert registered_page_candidates(None, None, 22, 'incoming', 0, 20, [],
                                          prepared=prepared) == expected
    assert len(calls) == 2
    with pytest.raises(ValueError, match='does not match'):
        registered_page_candidates(None, None, 23, 'incoming', 0, 20, [], prepared=prepared)


def test_merge_pages_requires_coverage_and_stable_provenance():
    common = {'body_id': '42', 'direction': 'incoming', 'source_md5': 'source',
              'morphology_sha256': 'skeleton', 'graph_manifest_sha256': 'graph',
              'source_coordinate_frame': '8nm'}
    first = {**common, 'offset': 0, 'next_offset': 20,
             'candidates': [{'partner_id': '11'}, {'partner_id': '11'}]}
    last = {**common, 'offset': 20, 'next_offset': None, 'candidates': [{'partner_id': '12'}]}
    assert merge_candidate_pages([first, last])['complete_graph_edge_coverage']
    partial = merge_candidate_pages([first], require_complete=False)
    assert not partial['complete_graph_edge_coverage']
    with pytest.raises(ValueError, match='cover all'):
        merge_candidate_pages([first])
    with pytest.raises(ValueError, match='incompatible'):
        merge_candidate_pages([first, {**last, 'offset': 21}])
    with pytest.raises(ValueError, match='incompatible'):
        merge_candidate_pages([first, {**last, 'morphology_sha256': 'other'}])
    with pytest.raises(ValueError, match='multiple pages'):
        merge_candidate_pages([first, {**last, 'candidates': [{'partner_id': '11'}]}])
    with pytest.raises(ValueError, match='incompatible'):
        merge_candidate_pages([first, last, last])
