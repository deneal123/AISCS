"""Check the common ideal-medium convention for stimulation and recording."""

import numpy as np
import pytest

pytest.importorskip("LFPy")

from service.contracts import Contact, Placement, SimulationConfig  # noqa: E402
from service.domain.model import Dynamics  # noqa: E402
from service.infrastructure.lfpy.recording import forward_recording  # noqa: E402
from service.infrastructure.stimulation.point_field import bipolar_potential_mv  # noqa: E402
from service.infrastructure.stimulation.reference_cable import simulate_reference_cable  # noqa: E402


def test_point_source_recording_and_bipolar_stimulation_obey_reciprocity():
    dynamics = Dynamics(
        np.array([0.0, 1.0]), np.zeros((1, 2)), np.array([[1.0, -1.0]]),
        np.array([[0.0, 0.0, -1.0]]), np.array([[0.0, 0.0, 1.0]]),
        np.array([1.0]), np.array([0]), [0], [], 0.0,
    )
    config = SimulationConfig(placement=Placement(
        electrode=Contact(x_um=10, y_um=0, z_um=0),
        reference=Contact(x_um=20, y_um=0, z_um=0),
    ))
    recorded_uv = forward_recording(config, dynamics)
    field_mv = bipolar_potential_mv(
        [[0, 0, 0]], [10, 0, 0], [20, 0, 0], 1,
        config.conductivity_s_m, clearance_um=2,
    )
    np.testing.assert_allclose(recorded_uv, [field_mv[0] * 1000, -field_mv[0] * 1000], rtol=1e-12)


def test_reference_cable_current_produces_location_dependent_recording():
    result = simulate_reference_cable(
        [0, 20, 0], [150, 20, 0], 1000, .3, clearance_um=2, nseg=25,
    )
    points = result["position_um"]
    delta = np.array([200 / (2 * len(points)), 0, 0])
    starts, ends = points - delta, points + delta
    dynamics = Dynamics(
        result["time_ms"], result["voltage_mv"], result["membrane_current_na"],
        starts, ends, np.ones(len(points)), np.zeros(len(points), dtype=int), [0], [], 0.0,
    )

    def record(y):
        config = SimulationConfig(placement=Placement(
            electrode=Contact(x_um=0, y_um=y, z_um=0),
            reference=Contact(x_um=150, y_um=20, z_um=0),
        ))
        return forward_recording(config, dynamics)

    near, far = record(20), record(80)
    assert np.isfinite(near).all() and np.isfinite(far).all()
    assert np.max(np.abs(near - far)) > .01
