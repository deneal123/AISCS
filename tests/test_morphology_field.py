import hashlib
import json

import numpy as np
import pytest

from service.infrastructure.connectome.morphology import _validated_nodes
from service.infrastructure.connectome.morphology_repository import BASE
from service.infrastructure.stimulation.morphology_field import (
    _geometry_from_validated_nodes,
    _parse_swc_geometry,
    evaluate_registered_neuron_field,
    evaluate_swc_field,
)

SWC = "1 1 0 0 0 1 -1\n2 3 125 0 0 1 1\n3 3 375 0 0 1 2\n4 3 750 0 0 1 3\n"


@pytest.mark.parametrize('swc', [SWC,
    '# comment\n10 3 -9.1 3e2 0 2.75 20\n20 1 2 -0.0 8 0 -1\n30 1 2 3 4 .01 -1\n'])
def test_validated_geometry_matches_original_parse_exactly(swc):
    original = _parse_swc_geometry(swc)
    actual = _geometry_from_validated_nodes(_validated_nodes(swc, include_radii=True))
    assert actual[0] == original[0]
    for expected, converted in zip(original[1:], actual[1:], strict=True):
        np.testing.assert_array_equal(converted, expected)


def evaluate(source, current=10):
    return evaluate_swc_field(SWC, source, [50, 10, 0], current, 0.3, clearance_um=1)


def test_source_coordinates_and_field_respond_to_stimulus_position_and_polarity():
    result = evaluate([0, 10, 0])
    np.testing.assert_allclose(result["points_um"][:, 0], [0, 1, 3, 6])
    np.testing.assert_array_equal(result["curvature_vertex_ids"], [2, 3])
    assert np.isfinite(result["curvature_mv_per_um2"]).all()
    moved = evaluate([10, 10, 0])
    assert not np.allclose(result["potential_mv"], moved["potential_mv"])
    reverse = evaluate([0, 10, 0], -10)
    np.testing.assert_allclose(reverse["curvature_mv_per_um2"], -result["curvature_mv_per_um2"])


def test_malformed_swc_and_contact_intersection_are_rejected():
    with pytest.raises(ValueError):
        evaluate_swc_field("not swc", [0, 10, 0], [50, 10, 0], 1, 0.3, clearance_um=1)
    with pytest.raises(ValueError, match="intersects"):
        evaluate([0, 0, 0])


def test_field_still_rejects_cyclic_topology_before_fast_curvature():
    swc = "1 1 0 0 0 1 -1\n2 3 125 0 0 1 3\n3 3 250 0 0 1 2\n"
    with pytest.raises(ValueError, match='Cyclic'):
        evaluate_swc_field(swc, [0, 10, 0], [50, 10, 0], 10, .3, clearance_um=1)


def test_contact_near_segment_interior_is_rejected_even_when_vertices_are_clear():
    long_edge = "1 1 0 0 0 1 -1\n2 3 12500 0 0 1 1\n"
    with pytest.raises(ValueError, match="cable segment"):
        evaluate_swc_field(long_edge, [50, 0, 0], [150, 30, 0], 10, 0.3, clearance_um=1)


def test_degenerate_edges_require_explicit_partial_mode_and_keep_other_curvatures():
    swc = ("1 1 0 0 0 125 -1\n2 3 125 0 0 125 1\n3 3 125 0 0 125 2\n"
           "4 3 250 0 0 125 3\n5 3 375 0 0 125 4\n6 3 500 0 0 125 5\n")
    args = (swc, [0, 10, 0], [50, 10, 0], 10, .3)
    with pytest.raises(ValueError, match="nonzero"):
        evaluate_swc_field(*args, clearance_um=1)
    result = evaluate_swc_field(*args, clearance_um=1, allow_degenerate=True)
    assert result["omitted_zero_length_edges"] == 1
    assert result["omitted_curvature_vertices"] == 2
    np.testing.assert_array_equal(result["curvature_vertex_ids"], [4, 5])
    assert len(result["potential_mv"]) == 6
    with pytest.raises(ValueError, match="degenerate"):
        evaluate_swc_field(swc, [1, 1.5, 0], [50, 10, 0], 10, .3,
                           clearance_um=1, allow_degenerate=True)


def test_isolated_vertex_radius_checked_in_common_field_operator():
    swc = SWC + "5 1 12500 0 0 125 -1\n"
    with pytest.raises(ValueError, match="isolated"):
        evaluate_swc_field(swc, [101.5, 0, 0], [150, 20, 0], 10, .3, clearance_um=1)


def test_registered_field_preserves_verified_identity_and_frame(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "receipts").mkdir()
    raw = SWC.encode()
    (tmp_path / "raw" / "42.swc").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    (tmp_path / "receipts" / "42.json").write_text(
        json.dumps({"body_id": 42, "url": BASE + "42.swc", "sha256": digest})
    )
    result = evaluate_registered_neuron_field(
        42, [tmp_path], [0, 10, 0], [50, 10, 0], 10, 0.3, clearance_um=1
    )
    assert result["source_sha256"] == digest and result["body_id"] == "42"
    assert result["coordinate_frame"] == "male-cns-v1.0-native-um"
    assert result["interpretation"] == "field-only"
    (tmp_path / "raw" / "42.swc").write_text("damaged")
    with pytest.raises(ValueError, match="failed validation"):
        evaluate_registered_neuron_field(
            42, [tmp_path], [0, 10, 0], [50, 10, 0], 10, 0.3, clearance_um=1
        )
