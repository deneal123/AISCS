import numpy as np
import pytest

from service.contracts import Contact, Placement, SimulationConfig
from service.domain.model import Dynamics
from service.infrastructure.lfpy.recording import (
    forward_recording,
    linesource_differential,
    pointsource_differential,
)
from service.infrastructure.stimulation.point_field import bipolar_potential_mv


def source():
    return Dynamics(
        np.array([0.0, 1.0]),
        np.zeros((1, 2)),
        np.array([[1.0, -1.0]]),
        np.array([[0.0, 0.0, -1.0]]),
        np.array([[0.0, 0.0, 1.0]]),
        np.array([1.0]),
        np.array([0]),
        [0],
        [],
        0.0,
    )


def test_pointsource_analytic_units_and_reference():
    cfg = SimulationConfig(
        placement=Placement(
            electrode=Contact(x_um=10, y_um=0, z_um=0), reference=Contact(x_um=20, y_um=0, z_um=0)
        )
    )
    signal = forward_recording(cfg, source())
    expected_uv = 1000 / (4 * np.pi * 0.3) * (1 / 10 - 1 / 20)
    np.testing.assert_allclose(signal, [expected_uv, -expected_uv], rtol=1e-12)


def test_reference_swap_inverts_sign():
    cfg = SimulationConfig()
    swapped = cfg.model_copy(
        update={
            "placement": Placement(
                electrode=cfg.placement.reference, reference=cfg.placement.electrode
            )
        }
    )
    np.testing.assert_allclose(
        forward_recording(cfg, source()), -forward_recording(swapped, source())
    )


def test_stimulation_and_point_recording_reciprocity_in_homogeneous_medium():
    rng = np.random.default_rng(31)
    midpoints = rng.uniform(-20, 20, size=(16, 3))
    currents = rng.uniform(-2, 2, size=(16, 5))
    offsets = np.tile([0., 0., .5], (len(midpoints), 1))
    dynamics = Dynamics(np.arange(5, dtype=float), np.zeros_like(currents), currents,
                        midpoints - offsets, midpoints + offsets, np.ones(len(midpoints)),
                        np.zeros(len(midpoints), dtype=int), [0], [], 0.)
    contacts = np.array([[100., 30., 20.], [-80., -20., 10.]])
    recorded = pointsource_differential(dynamics, contacts, 0.3)
    reciprocal_field = bipolar_potential_mv(midpoints, contacts[0], contacts[1], 1., .3,
                                            clearance_um=1.)
    # 1 nA injected across the contacts produces mV at each source. The same
    # transfer coefficients convert membrane nA to mV at the contacts; the
    # recorder reports microvolts.
    np.testing.assert_allclose(recorded, reciprocal_field @ currents * 1000, rtol=1e-12, atol=1e-12)


def test_contact_inside_source_rejected():
    cfg = SimulationConfig(placement=Placement(electrode=Contact(x_um=0, y_um=0, z_um=0)))
    with pytest.raises(ValueError, match="outside"):
        forward_recording(cfg, source())


def test_invalid_source_geometry_cannot_bypass_contact_clearance():
    cfg = SimulationConfig()
    invalid = source()
    invalid.ends_um = invalid.starts_um.copy()
    with pytest.raises(ValueError, match="nonzero length"):
        forward_recording(cfg, invalid)
    invalid = source()
    invalid.diameters_um[0] = np.nan
    with pytest.raises(ValueError, match="geometry"):
        forward_recording(cfg, invalid)


def test_multiple_sources_superpose_and_scale_with_conductivity():
    first = source()
    second = source()
    second.starts_um = np.array([[0.0, 10.0, -1.0]])
    second.ends_um = np.array([[0.0, 10.0, 1.0]])
    second.membrane_current_na = np.array([[2.0, -3.0]])
    combined = source()
    combined.starts_um = np.concatenate([first.starts_um, second.starts_um])
    combined.ends_um = np.concatenate([first.ends_um, second.ends_um])
    combined.diameters_um = np.concatenate([first.diameters_um, second.diameters_um])
    combined.membrane_current_na = np.concatenate(
        [first.membrane_current_na, second.membrane_current_na]
    )
    cfg = SimulationConfig(
        placement=Placement(
            electrode=Contact(x_um=50, y_um=0, z_um=0), reference=Contact(x_um=100, y_um=0, z_um=0)
        )
    )
    actual = forward_recording(cfg, combined)
    np.testing.assert_allclose(
        actual, forward_recording(cfg, first) + forward_recording(cfg, second), rtol=1e-12
    )
    doubled = cfg.model_copy(update={"conductivity_s_m": 0.6})
    np.testing.assert_allclose(forward_recording(doubled, combined), actual / 2, rtol=1e-12)


def test_point_source_mesh_converges_to_uniform_line_integral():
    length = 100.0
    cfg = SimulationConfig(
        placement=Placement(
            electrode=Contact(x_um=20, y_um=0, z_um=0),
            reference=Contact(x_um=100, y_um=0, z_um=0),
        )
    )

    def line(radius):
        return 2 * np.arcsinh(length / (2 * radius)) / length

    expected = 1000 * (line(20) - line(100)) / (4 * np.pi * cfg.conductivity_s_m)
    errors = []
    for count in (5, 15, 45):
        bounds = np.linspace(-length / 2, length / 2, count + 1)
        model = source()
        model.starts_um = np.column_stack((np.zeros(count), np.zeros(count), bounds[:-1]))
        model.ends_um = np.column_stack((np.zeros(count), np.zeros(count), bounds[1:]))
        model.diameters_um = np.ones(count)
        model.membrane_current_na = np.tile([1 / count, -1 / count], (count, 1))
        actual = forward_recording(cfg, model)
        np.testing.assert_allclose(actual[0], -actual[1], rtol=1e-12)
        errors.append(abs(actual[0] - expected) / abs(expected))
    assert errors[2] < errors[1] < errors[0]
    assert errors[2] < 0.0001


def test_line_source_matches_analytic_integral_and_contact_reversal():
    model = source()
    model.starts_um = np.array([[0., 0., -50.]])
    model.ends_um = np.array([[0., 0., 50.]])
    points = np.array([[20., 0., 0.], [100., 0., 0.]])
    signal = linesource_differential(model, points, 0.3)
    def line(radius):
        return 2 * np.arcsinh(50 / radius) / 100
    expected = 1000 * (line(20) - line(100)) / (4 * np.pi * 0.3)
    np.testing.assert_allclose(signal, [expected, -expected], rtol=1e-12)
    np.testing.assert_allclose(linesource_differential(model, points[::-1], 0.3), -signal)
