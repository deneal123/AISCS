"""Path-free experimental electrical field-to-graph request contract."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from pydantic import Field, model_validator

from service.contracts import Contract, Finite
from service.domain.contracts.replay import ReplaySimulation, ReplaySynapse


class FieldGraphCell(Contract):
    body_id: int = Field(strict=True, gt=0, lt=2**63)
    child_node_id: int = Field(strict=True, gt=0, lt=2**63)
    threshold_mv: Finite
    sampling_fraction: Finite | None = Field(default=None, ge=0, le=1)
    morphology_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class FieldGraphAcquisition(Contract):
    low_hz: Finite
    high_hz: Finite
    recovery_ms: Finite
    clip_uv: Finite | None = None

    @model_validator(mode="after")
    def valid_acquisition(self):
        if (
            not 0 < self.low_hz < self.high_hz
            or self.recovery_ms < 0
            or (self.clip_uv is not None and self.clip_uv <= 0)
        ):
            raise ValueError("Invalid acquisition settings")
        return self


class FieldGraphConfig(Contract):
    graph_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_cells: list[FieldGraphCell] = Field(min_length=1)
    replay_ids: list[int] = Field(min_length=1)
    seed: int = Field(strict=True, ge=0, le=2**31 - 1)
    simulation: ReplaySimulation
    synapse: ReplaySynapse
    acquisition: FieldGraphAcquisition | None = None
    retain_currents: bool | None = Field(default=None, strict=True)
    retain_state_contrast: bool | None = Field(default=None, strict=True)
    retain_compartment_crossings: bool | None = Field(default=None, strict=True)

    @model_validator(mode="before")
    @classmethod
    def replay_ids_are_strict_integers(cls, value):
        if isinstance(value, dict):
            ids = value.get("replay_ids")
            if isinstance(ids, list) and any(type(body) is not int for body in ids):
                raise ValueError("Replay IDs must be integers")
        return value

    @model_validator(mode="after")
    def consistent(self):
        source_ids = [cell.body_id for cell in self.source_cells]
        if (
            any(not 0 < body < 2**63 for body in self.replay_ids)
            or len(set(source_ids)) != len(source_ids)
            or len(set(self.replay_ids)) != len(self.replay_ids)
            or set(source_ids).intersection(self.replay_ids)
        ):
            raise ValueError("Cell sets must contain distinct disjoint IDs")
        duration = self.simulation.duration_ms
        if not duration.is_integer() or not 1 <= duration <= 1000:
            raise ValueError("Graph duration must be an integer between 1 and 1000 ms")
        if self.acquisition and self.acquisition.high_hz >= 500 / self.simulation.dt_ms:
            raise ValueError("Acquisition bandwidth exceeds Nyquist frequency")
        return self

    def digest(self):
        encoded = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def execution_parameters(self):
        simulation = self.simulation.model_dump(
            exclude={
                "electrode_um",
                "reference_um",
                "coordinate_frame",
                "source_model",
            }
        )
        acquisition = (
            None
            if self.acquisition is None
            else {
                "low_hz": self.acquisition.low_hz,
                "high_hz": self.acquisition.high_hz,
                "recovery_ms": self.acquisition.recovery_ms,
                "clip_uv": self.acquisition.clip_uv,
            }
        )
        return {
            "source_cells": [cell.model_dump() for cell in self.source_cells],
            "replay_ids": self.replay_ids.copy(),
            "seed": self.seed,
            "simulation_parameters": simulation,
            "schedule_parameters": {
                **self.synapse.model_dump(),
                "duration_ms": self.simulation.duration_ms,
            },
            "recording": {
                "electrode_um": list(self.simulation.electrode_um),
                "reference_um": list(self.simulation.reference_um),
                "source_model": self.simulation.source_model,
            },
            "acquisition": acquisition,
            **({"retain_compartment_crossings": True}
               if self.retain_compartment_crossings is True else {}),
        }


class FieldGraphExecutionRequest(Contract):
    execution_id: UUID
    config: FieldGraphConfig
