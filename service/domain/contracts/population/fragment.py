"""Explicit subset contract for experimental fragment-local propagation."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from pydantic import Field, model_validator

from service.contracts import Contract, Finite
from service.domain.contracts.replay import ReplaySimulation


class FragmentPopulationConfig(Contract):
    graph_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_ids: list[int] = Field(min_length=1, max_length=256)
    seed: int = Field(strict=True, ge=0, le=2**31 - 1)
    simulation: ReplaySimulation
    threshold_mv: Finite
    max_distance_um: Finite = Field(ge=0)
    allow_partial_geometry: bool | None = Field(default=None, strict=True)

    @model_validator(mode="before")
    @classmethod
    def strict_ids(cls, value):
        if isinstance(value, dict) and isinstance(value.get("source_ids"), list):
            if any(type(body) is not int for body in value["source_ids"]):
                raise ValueError("Source IDs must be integers")
        return value

    @model_validator(mode="after")
    def consistency(self):
        if any(not 0 < body < 2**63 for body in self.source_ids) or len(
            set(self.source_ids)
        ) != len(self.source_ids):
            raise ValueError("Source IDs must be positive and distinct")
        if (
            not self.simulation.allow_disconnected
            or not self.simulation.duration_ms.is_integer()
            or not 1 <= self.simulation.duration_ms <= 1000
        ):
            raise ValueError(
                "Fragment mode needs disconnected-fragment support and integer duration"
            )
        return self

    def digest(self):
        data = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf8")
        return hashlib.sha256(data).hexdigest()

    def execution_parameters(self):
        result = {
            "source_ids": self.source_ids.copy(),
            "seed": self.seed,
            "threshold_mv": self.threshold_mv,
            "max_distance_um": self.max_distance_um,
            "simulation_parameters": self.simulation.model_dump(
                exclude={"electrode_um", "reference_um", "coordinate_frame", "source_model"}
            ),
            "electrode_um": list(self.simulation.electrode_um),
            "reference_um": list(self.simulation.reference_um),
            "source_model": self.simulation.source_model,
        }
        if self.allow_partial_geometry is not None:
            result["allow_partial_geometry"] = self.allow_partial_geometry
        return result


class FragmentPopulationExecutionRequest(Contract):
    execution_id: UUID
    config: FragmentPopulationConfig
