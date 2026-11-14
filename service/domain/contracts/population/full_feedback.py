"""Path-free request for experimental full detailed-cell feedback."""

import hashlib
import json
from uuid import UUID

from pydantic import Field, model_validator

from service.contracts import Contract, Finite
from service.domain.contracts.population.feedback import FeedbackSynapse
from service.domain.contracts.replay import ReplaySimulation


class FullFeedbackConfig(Contract):
    graph_manifest_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    simulation: ReplaySimulation
    excitatory: FeedbackSynapse
    inhibitory: FeedbackSynapse
    threshold_mv: Finite = Field(ge=-200, le=100)
    max_source_distance_um: Finite = Field(ge=0, le=100)
    max_target_distance_um: Finite = Field(ge=0, le=100)
    max_iterations: int = Field(strict=True, ge=1, le=100)
    max_events: int = Field(strict=True, ge=1, le=1_000_000_000)
    allow_known_geometry_repair: bool = Field(strict=True, default=False)

    @model_validator(mode='after')
    def supported_simulation(self):
        simulation = self.simulation
        if (simulation.duration_ms != int(simulation.duration_ms)
                or simulation.duration_ms < 1 or simulation.nseg_per_edge != 1
                or simulation.source_model != 'pointsource'
                or simulation.dt_ms not in (.025, .05) or not simulation.allow_disconnected):
            raise ValueError('Unsupported simulation for full detailed feedback')
        return self

    def parameters(self):
        return {1: self.excitatory.model_dump(mode='json'),
                -1: self.inhibitory.model_dump(mode='json')}

    def digest(self):
        payload = json.dumps(self.model_dump(mode='json'), sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf8')
        return hashlib.sha256(payload).hexdigest()


class FullFeedbackExecutionRequest(Contract):
    execution_id: UUID
    config: FullFeedbackConfig
