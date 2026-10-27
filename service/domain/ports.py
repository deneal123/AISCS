from pathlib import Path
from typing import Protocol

import numpy as np

from service.contracts import SimulationConfig
from service.domain.model import Dynamics


class NumericalEngine(Protocol):
    def simulate(self, config: SimulationConfig) -> Dynamics: ...


class RecordingOperator(Protocol):
    def record(self, config: SimulationConfig, dynamics: Dynamics) -> np.ndarray: ...


class ArtifactWriter(Protocol):
    def write(self, config: SimulationConfig, dynamics: Dynamics, directory: Path) -> dict: ...
