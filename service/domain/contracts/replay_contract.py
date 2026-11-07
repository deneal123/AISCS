"""Validated, path-free inputs for an isolated registered-cell replay."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from service.contracts import Contract, Finite


class ReplaySynapse(Contract):
    delay_ms: Finite
    weight_us: Finite
    tau1_ms: Finite
    tau2_ms: Finite
    reversal_mv: Finite

    @model_validator(mode="after")
    def valid_kinetics(self):
        if (self.delay_ms < 0 or self.weight_us <= 0 or not 0 < self.tau1_ms < self.tau2_ms
                or not 1e-9 <= self.tau1_ms / self.tau2_ms <= .9999):
            raise ValueError("Invalid synaptic delay, conductance or time constants")
        return self


class ReplaySimulation(Contract):
    source_um: tuple[Finite, Finite, Finite]
    return_um: tuple[Finite, Finite, Finite]
    electrode_um: tuple[Finite, Finite, Finite]
    reference_um: tuple[Finite, Finite, Finite]
    current_na: Finite
    conductivity_s_m: Finite
    clearance_um: Finite
    duration_ms: Finite
    dt_ms: Finite
    pulse_start_ms: Finite
    pulse_end_ms: Finite
    rise_time_ms: Finite
    interphase_gap_ms: Finite
    pulse_shape: Literal["monophasic", "biphasic"]
    pulse_count: int | None = Field(default=None, strict=True, ge=2, le=1000)
    pulse_interval_ms: Finite | None = None
    nseg_per_edge: int = Field(strict=True, gt=0)
    allow_disconnected: bool = Field(strict=True)
    source_model: Literal["pointsource", "linesource"]
    coordinate_frame: Literal["male-cns-v1.0-native-um"]

    @model_validator(mode="after")
    def valid_geometry_and_timing(self):
        from service.domain.pulse_train import pulse_train

        if (self.source_um == self.return_um or self.electrode_um == self.reference_um
                or self.conductivity_s_m <= 0 or self.clearance_um <= 0
                or self.dt_ms <= 0 or self.duration_ms <= 0
                or not 0 < self.pulse_start_ms < self.pulse_end_ms < self.duration_ms
                or self.rise_time_ms < 0
                or 2 * self.rise_time_ms > self.pulse_end_ms - self.pulse_start_ms
                or self.interphase_gap_ms < 0 or self.nseg_per_edge % 2 != 1
                or (self.pulse_shape == "monophasic" and self.interphase_gap_ms != 0)
                or (self.pulse_shape == "biphasic" and self.pulse_end_ms + self.interphase_gap_ms
                    + self.pulse_end_ms - self.pulse_start_ms >= self.duration_ms)):
            raise ValueError("Invalid replay geometry or timing")
        ratio = self.duration_ms / self.dt_ms
        if not math.isfinite(ratio) or not math.isclose(round(ratio) * self.dt_ms,
                            self.duration_ms, rel_tol=0, abs_tol=1e-9):
            raise ValueError("Duration must be divisible by time step")
        if (self.pulse_count is None) != (self.pulse_interval_ms is None):
            raise ValueError('Pulse count and interval must be specified together')
        pulse_train(start_ms=self.pulse_start_ms, end_ms=self.pulse_end_ms,
                    rise_ms=self.rise_time_ms, interphase_gap_ms=self.interphase_gap_ms,
                    shape=self.pulse_shape, duration_ms=self.duration_ms,
                    count=self.pulse_count or 1, interval_ms=self.pulse_interval_ms)
        return self


class ReplayRunConfig(Contract):
    source_run_id: UUID
    graph_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    body_id: int = Field(strict=True, gt=0, lt=2**63)
    synapse: ReplaySynapse
    simulation: ReplaySimulation

    def digest(self):
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def execution_parameters(self):
        """Build solver inputs without passing user-controlled filesystem paths."""
        simulation = self.simulation.model_dump(exclude={
            "electrode_um", "reference_um", "coordinate_frame", "source_model",
        })
        schedule = {**self.synapse.model_dump(), "duration_ms": self.simulation.duration_ms}
        return {"body_id": self.body_id, "simulation_parameters": simulation,
                "schedule_parameters": schedule, "electrode_um": self.simulation.electrode_um,
                "reference_um": self.simulation.reference_um,
                "source_model": self.simulation.source_model,
                "source_run_id": str(self.source_run_id),
                "graph_manifest_sha256": self.graph_manifest_sha256,
                "configuration_sha256": self.digest()}


class ReplayExecutionRequest(Contract):
    execution_id: UUID
    config: ReplayRunConfig
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_description: dict

    @model_validator(mode="after")
    def matching_graph(self):
        if self.source_description.get("manifest_sha256") != self.config.graph_manifest_sha256:
            raise ValueError("Replay source graph does not match configuration")
        return self
