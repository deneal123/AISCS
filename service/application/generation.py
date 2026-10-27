from dataclasses import dataclass
from pathlib import Path

from service.contracts import SimulationConfig
from service.domain.ports import ArtifactWriter, NumericalEngine


@dataclass
class GenerateSignal:
    engine: NumericalEngine
    writer: ArtifactWriter

    def execute(self, config: SimulationConfig, directory: Path) -> dict:
        dynamics = self.engine.simulate(config)
        return self.writer.write(config, dynamics, directory)
