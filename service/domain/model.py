from dataclasses import dataclass

import numpy as np


@dataclass
class Dynamics:
    time_ms: np.ndarray
    voltage_mv: np.ndarray
    membrane_current_na: np.ndarray
    starts_um: np.ndarray
    ends_um: np.ndarray
    diameters_um: np.ndarray
    cell_ids: np.ndarray
    soma_segment_ids: list[int]
    spikes: list[dict]
    seconds: float
    cache_info: dict | None = None
    input_events: list[dict] | None = None
    connectome: dict | None = None
