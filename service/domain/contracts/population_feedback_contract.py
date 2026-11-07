"""Explicit settings for an experimental coupled population calculation."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from pydantic import Field, model_serializer, model_validator

from service.contracts import Contract, Finite


class FeedbackSynapse(Contract):
    weight_us: Finite = Field(gt=0)
    tau1_ms: Finite = Field(gt=0)
    tau2_ms: Finite = Field(gt=0)
    reversal_mv: Finite

    @model_validator(mode='after')
    def kinetics(self):
        if not 1e-9 <= self.tau1_ms / self.tau2_ms <= .9999:
            raise ValueError('Invalid feedback kinetics')
        return self


class FeedbackDiscretization(Contract):
    """Explicit geometric limits; these do not assert physical convergence."""

    max_shift_um: Finite = Field(ge=0, le=100)
    max_observation_distance_um: Finite = Field(ge=0, le=100)
    max_nseg: int = Field(strict=True, ge=1, le=101)

    @model_validator(mode='after')
    def odd_segments(self):
        if self.max_nseg % 2 != 1:
            raise ValueError('Maximum segment count must be odd')
        return self


class PopulationFeedbackConfig(Contract):
    graph_manifest_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_package_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_manifest_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    excitatory: FeedbackSynapse
    inhibitory: FeedbackSynapse
    max_iterations: int = Field(strict=True, ge=1, le=100)
    allow_partial_geometry: bool = Field(strict=True)
    discretization: FeedbackDiscretization | None = None

    @model_serializer(mode='wrap')
    def preserve_legacy_configuration(self, handler):
        data = handler(self)
        if self.discretization is None:
            data.pop('discretization', None)
        return data

    def digest(self):
        payload = json.dumps(self.model_dump(mode='json'), sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf8')
        return hashlib.sha256(payload).hexdigest()

    def parameters(self):
        return {1: self.excitatory.model_dump(mode='json'),
                -1: self.inhibitory.model_dump(mode='json')}


class PopulationFeedbackExecutionRequest(Contract):
    execution_id: UUID
    config: PopulationFeedbackConfig
