"""Explicit, bounded one-way replay of selected sources onto one target."""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from service.contracts import Contract, Finite
from service.domain.contracts.replay_contract import ReplaySynapse


class PopulationTargetConfig(Contract):
    graph_manifest_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_package_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_manifest_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    target_id: int = Field(strict=True, gt=0, lt=2**63)
    source_ids: list[int] = Field(min_length=1, max_length=256)
    synapses: list[ReplaySynapse] = Field(min_length=1, max_length=256)
    duration_ms: int = Field(strict=True, ge=1, le=1000)
    max_target_distance_um: Finite = Field(ge=0)
    max_events: int = Field(strict=True, ge=1, le=1_000_000)
    timing_mode: Literal['upper_bound', 'lower_bound'] | None = None

    @model_validator(mode='before')
    @classmethod
    def strict_ids(cls, value):
        if isinstance(value, dict) and isinstance(value.get('source_ids'), list):
            if any(type(body) is not int for body in value['source_ids']):
                raise ValueError('Source IDs must be integers')
        return value

    @model_validator(mode='after')
    def consistent(self):
        if (any(not 0 < body < 2**63 for body in self.source_ids)
                or len(set(self.source_ids)) != len(self.source_ids)
                or self.target_id in self.source_ids or len(self.source_ids) != len(self.synapses)):
            raise ValueError('Invalid source/target selection or synaptic parameters')
        return self

    def digest(self):
        data = json.dumps(self.model_dump(mode='json'), sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf8')
        return hashlib.sha256(data).hexdigest()

    def schedules(self):
        return [{**synapse.model_dump(mode='json'), 'duration_ms': self.duration_ms}
                for synapse in self.synapses]


class PopulationTargetExecutionRequest(Contract):
    execution_id: UUID
    config: PopulationTargetConfig
