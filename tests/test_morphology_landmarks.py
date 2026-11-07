import math

import pytest

from service.infrastructure.connectome.morphology import neurite_landmark


def test_landmark_is_an_actual_vertex_nearest_cable_centroid_not_a_soma_estimate():
    # Native coordinates are 8nm units. The long final edge shifts the centroid;
    # simply averaging vertices or choosing the SWC root gives a different point.
    text = "1 0 0 0 0 1 -1\n2 0 1 0 0 1 1\n3 0 2 0 0 1 2\n4 0 100 0 0 1 3\n"
    result = neurite_landmark(text)
    assert result["swc_vertex"] == 3
    assert result["anchor_um"] == [0.016, 0, 0]
    assert math.isclose(result["cable_length_um"], 0.8)
    assert result["bounds_um"] == [[0, 0.8], [0, 0], [0, 0]]
    assert result["vertices"] == 4 and result["components"] == 1


def test_row_order_and_branch_density_do_not_change_the_reconstructed_cable():
    text = "5 0 0 0 0 1 -1\n8 0 100 0 0 1 5\n12 0 100 100 0 1 8"
    a = neurite_landmark(text)
    b = neurite_landmark("\n".join(reversed(text.splitlines())))
    assert a == b
    assert a["swc_vertex"] == 8
    assert a["anchor_um"] == [0.8, 0, 0]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "1 0 0 0 0 1",
        "1 0 nan 0 0 1 -1",
        "1 0 0 0 0 -1 -1",
        "1 0 0 0 0 1 1",
        "1 0 0 0 0 1 3",
        "1 0 0 0 0 1 -1\n1 0 0 0 0 1 -1",
        "1 0 0 0 0 1 2\n2 0 0 0 0 1 1",
    ],
)
def test_invalid_morphology_is_rejected_instead_of_creating_fake_coordinates(text):
    with pytest.raises(ValueError):
        neurite_landmark(text)


def test_fragmented_and_single_point_reconstructions_remain_explicit():
    result = neurite_landmark("1 0 0 0 0 1 -1\n2 0 0 100 0 1 -1")
    assert result["components"] == 2 and result["cable_length_um"] == 0
    assert result["anchor_um"] == [0, 0, 0]
