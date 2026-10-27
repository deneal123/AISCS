import numpy as np
import pytest

from service.contracts import Contact, Placement, SimulationConfig
from service.domain.model import Dynamics
from service.infrastructure.lfpy.recording import forward_recording


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


def test_contact_inside_source_rejected():
    cfg = SimulationConfig(placement=Placement(electrode=Contact(x_um=0, y_um=0, z_um=0)))
    with pytest.raises(ValueError, match="outside"):
        forward_recording(cfg, source())
