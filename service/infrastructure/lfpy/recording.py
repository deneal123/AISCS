import numpy as np

from service.contracts import SimulationConfig
from service.domain.model import Dynamics
from service.domain.placement import validate_contacts


def pointsource_differential(
    dynamics: Dynamics, points: np.ndarray, conductivity_s_m: float
) -> np.ndarray:
    return _differential(dynamics, points, conductivity_s_m, "pointsource")


def linesource_differential(
    dynamics: Dynamics, points: np.ndarray, conductivity_s_m: float
) -> np.ndarray:
    """Uniform current along each segment in an infinite homogeneous medium."""
    return _differential(dynamics, points, conductivity_s_m, "linesource")


def _differential(
    dynamics: Dynamics, points: np.ndarray, conductivity_s_m: float, method: str
) -> np.ndarray:
    from LFPy import RecExtElectrode
    from lfpykit import CellGeometry

    coords = np.stack([dynamics.starts_um, dynamics.ends_um], axis=2)
    geometry = CellGeometry(x=coords[:, 0], y=coords[:, 1], z=coords[:, 2], d=dynamics.diameters_um)
    probe = RecExtElectrode(
        cell=geometry,
        sigma=conductivity_s_m,
        x=points[:, 0],
        y=points[:, 1],
        z=points[:, 2],
        method=method,
    )
    # nA and um yield mV; UI/export channel is explicitly converted to microvolts.
    matrix = probe.get_transformation_matrix()
    return (matrix[0] - matrix[1]) @ dynamics.membrane_current_na * 1000


def forward_recording(config: SimulationConfig, dynamics: Dynamics) -> np.ndarray:
    validate_contacts(config, dynamics.starts_um, dynamics.ends_um, dynamics.diameters_um)
    points = np.array([config.placement.electrode.xyz(), config.placement.reference.xyz()])
    return pointsource_differential(dynamics, points, config.conductivity_s_m)


class LFPyRecorder:
    record = staticmethod(forward_recording)
