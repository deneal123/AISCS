import numpy as np
import pytest

from service.infrastructure.stimulation.point_field import (
    bipolar_potential_mv,
    cable_curvature_mv_per_um2,
    neurite_curvature_mv_per_um2,
    validate_segment_clearance,
)


def field(points, source=(0, 0, 0), ret=(100, 0, 0), current=1, sigma=0.3):
    return bipolar_potential_mv(points, source, ret, current, sigma, clearance_um=1)


def test_segment_clearance_includes_taper_and_endpoints():
    starts, ends = [[0, 0, 0]], [[10, 0, 0]]
    radii = [[0.5, 2]]
    validate_segment_clearance(starts, ends, [[5, 4, 0]], 1, radii)
    with pytest.raises(ValueError, match="cable segment"):
        validate_segment_clearance(starts, ends, [[5, 2.9, 0]], 1, radii)
    with pytest.raises(ValueError, match="cable segment"):
        validate_segment_clearance(starts, ends, [[10, 0, 0]], 1, radii)
    with pytest.raises(ValueError, match="nonzero"):
        validate_segment_clearance(starts, starts, [[5, 4, 0]], 1, radii)


def test_branched_unequal_spacing_matches_independent_scalar_calculation():
    rng = np.random.default_rng(42)
    parents = np.array([-1, 0, 1, 1, 2, 3, 4, 6, 7], dtype=np.int64)
    points = rng.uniform(0, 10, (len(parents), 3))
    potential = rng.normal(size=len(parents))
    expected_indices, expected_values = [], []
    for node, parent in enumerate(parents):
        children = np.flatnonzero(parents == node)
        if parent < 0 or len(children) != 1:
            continue
        child = children[0]
        before = np.linalg.norm(points[node] - points[parent])
        after = np.linalg.norm(points[child] - points[node])
        expected_indices.append(node)
        gradient = ((potential[child] - potential[node]) / after
                    - (potential[node] - potential[parent]) / before)
        expected_values.append(2 * gradient / (before + after))
    actual_indices, actual_values = neurite_curvature_mv_per_um2(points, parents, potential)
    np.testing.assert_array_equal(actual_indices, expected_indices)
    np.testing.assert_allclose(actual_values, expected_values, rtol=1e-14)


def test_point_sources_have_analytic_units_and_superposition():
    points = np.array([[10, 0, 0], [20, 0, 0], [50, 10, 0]], dtype=float)
    expected = np.array([1 / 10 - 1 / 90, 1 / 20 - 1 / 80, 0]) / (4 * np.pi * 0.3)
    np.testing.assert_allclose(field(points), expected, atol=1e-15)
    np.testing.assert_allclose(field(points, current=3), 3 * expected)
    np.testing.assert_allclose(field(points, sigma=0.6), expected / 2)
    np.testing.assert_allclose(field(points, source=(100, 0, 0), ret=(0, 0, 0)), -expected)
    np.testing.assert_allclose(field(points, current=0), np.zeros(3))


def test_field_rejects_numeric_overflow():
    with np.errstate(over='ignore', invalid='ignore'):
        with pytest.raises(ValueError, match='distance overflow'):
            field([[1e308, 0, 0]])
        with pytest.raises(ValueError, match='Potential overflow'):
            field([[10, 0, 0]], current=1e308, sigma=1e-300)
        with pytest.raises(ValueError, match='distance overflow'):
            field(np.empty((0, 3)), source=(1e308, 0, 0), ret=(-1e308, 0, 0))
        with pytest.raises(ValueError, match='Potential overflow'):
            field(np.empty((0, 3)), current=1e308, sigma=1e-300)
    with pytest.raises(ValueError, match='curvature overflow'):
        cable_curvature_mv_per_um2([1e308, -1e308, 1e308], 1.0)
    with pytest.raises(ValueError, match='curvature overflow'):
        cable_curvature_mv_per_um2([1.0, 2.0, 3.0], 1e-300)


def test_invalid_gpu_field_is_rejected_before_cuda_is_required():
    from service.infrastructure.stimulation.point_field_gpu import bipolar_potential_mv_gpu

    with pytest.raises(ValueError, match='Potential overflow'):
        bipolar_potential_mv_gpu(np.empty((0, 3)), [0, 0, 0], [100, 0, 0],
                                 1e308, 1e-300, clearance_um=1)


def test_neurite_curvature_uses_actual_unequal_spacing_and_excludes_branches():
    x = np.array([0., 1., 3., 6., 7., 7.])
    points = np.column_stack((x, np.array([0., 0., 0., 0., 1., -1.]), np.zeros(6)))
    parents = np.array([-1, 0, 1, 2, 3, 3])
    indices, values = neurite_curvature_mv_per_um2(points, parents, x**2 + 17)
    np.testing.assert_array_equal(indices, [1, 2])
    np.testing.assert_allclose(values, [2, 2])
    _, linear = neurite_curvature_mv_per_um2(points, parents, x * 3 + 9)
    np.testing.assert_allclose(linear, 0)


def test_neurite_curvature_rejects_cycles_and_duplicate_coordinates():
    with pytest.raises(ValueError, match='Cyclic'):
        neurite_curvature_mv_per_um2([[0, 0, 0], [1, 0, 0]], [1, 0], [0, 1])
    with pytest.raises(ValueError, match='Zero-length'):
        neurite_curvature_mv_per_um2([[0, 0, 0], [0, 0, 0], [1, 0, 0]], [-1, 0, 1], [0, 0, 1])


def test_cable_curvature_converges_to_analytic_second_derivative():
    # Along x at y=10, second derivative of 1/r is (2*x**2 - y**2)/r**5.
    def one_contact(x, y):
        return (2 * x**2 - y**2) / (x**2 + y**2) ** 2.5

    x, y = 20.0, 10.0
    expected = (one_contact(x, y) - one_contact(x - 100, y)) / (4 * np.pi * 0.3)
    errors = []
    for step in (2.0, 1.0, 0.5):
        points = [[x - step, y, 0], [x, y, 0], [x + step, y, 0]]
        result = cable_curvature_mv_per_um2(field(points), step)[0]
        errors.append(abs(result - expected))
    assert errors[2] < errors[1] < errors[0]
    assert errors[2] / abs(expected) < 0.001


def test_curvature_is_invariant_to_reference_offset_and_linear_potential():
    data = np.array([1.0, 2.0, 4.0, 7.0])
    expected = cable_curvature_mv_per_um2(data, 2)
    np.testing.assert_allclose(cable_curvature_mv_per_um2(data + 100, 2), expected)
    np.testing.assert_allclose(cable_curvature_mv_per_um2(np.arange(4.0), 2), 0)


@pytest.mark.parametrize("point", [[[0, 0, 0]], [[100, 0, 0]], [[np.nan, 0, 0]], [[0, 0]]])
def test_invalid_or_singular_observation_is_rejected(point):
    with pytest.raises(ValueError):
        field(point)


@pytest.mark.parametrize("current,sigma,clearance", [(1, 0, 1), (1, -1, 1), (1, 0.3, 0),
                                                       (np.nan, 0.3, 1), (True, 0.3, 1)])
def test_invalid_scalar_parameters_are_rejected(current, sigma, clearance):
    with pytest.raises(ValueError):
        bipolar_potential_mv([[10, 0, 0]], [0, 0, 0], [100, 0, 0], current, sigma,
                             clearance_um=clearance)


def test_overlapping_contacts_and_bad_cable_are_rejected():
    with pytest.raises(ValueError):
        field([[10, 0, 0]], ret=(1, 0, 0))
    with pytest.raises(ValueError):
        cable_curvature_mv_per_um2([1, 2], 1)
    with pytest.raises(ValueError):
        cable_curvature_mv_per_um2([1, 2, 3], 0)
