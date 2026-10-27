"""Bounded scientific contract. Coordinates are physical model coordinates, in micrometres."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

Finite = Annotated[float, Field(allow_inf_nan=False, strict=True)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)

    @model_serializer(mode="wrap")
    def serialize_without_absent_context(self, handler):
        # New optional provenance must preserve canonical hashes of legacy inputs.
        return {key: value for key, value in handler(self).items() if value is not None}


class SurfaceAnchor(Contract):
    mesh_part: str = Field(max_length=100)
    triangle: int = Field(strict=True, ge=0)
    barycentric: tuple[Finite, Finite, Finite]

    @model_validator(mode="after")
    def inside_triangle(self):
        if abs(sum(self.barycentric) - 1) > 1e-5 or any(
            value < -1e-6 or value > 1 + 1e-6 for value in self.barycentric
        ):
            raise ValueError("Anchor must lie inside the selected mesh triangle")
        return self


class RegistrationContext(Contract):
    mesh_asset_id: str
    mesh_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    region_id: str
    mesh_part: str
    mesh_triangle_count: int = Field(strict=True, ge=1)
    origin_mm: tuple[Finite, Finite, Finite]
    mesh_units: str
    model_units: str
    um_to_mm: Finite
    bridge_kind: str
    attachment: str
    contact_shape: str
    operator_version: str
    surface_anchor: SurfaceAnchor | None = None

    @model_validator(mode="after")
    def registered_transform(self):
        from service.domain.scene_context import registered_scene_contexts

        registered = registered_scene_contexts()
        if self.model_dump(mode="json", exclude={"surface_anchor"}) not in registered:
            raise ValueError("Unregistered anatomical context or physical transform")
        if self.surface_anchor and (
            self.surface_anchor.mesh_part != self.mesh_part
            or self.surface_anchor.triangle >= self.mesh_triangle_count
        ):
            raise ValueError("Unregistered surface anchor")
        return self


class Contact(Contract):
    x_um: Finite = Field(default=0, ge=-500, le=500)
    y_um: Finite = Field(default=90, ge=-500, le=500)
    z_um: Finite = Field(default=40, ge=-500, le=500)

    def xyz(self) -> list[float]:
        return [self.x_um, self.y_um, self.z_um]


class Placement(Contract):
    region_id: Literal["thoracic-local-v1"] = "thoracic-local-v1"
    electrode: Contact = Field(default_factory=Contact)
    reference: Contact = Field(default_factory=lambda: Contact(x_um=300, y_um=250, z_um=100))
    mesh_asset_id: str = Field(default="schematic-fly-v1", max_length=100)
    transform_version: Literal["thoracic-rigid-v1"] = "thoracic-rigid-v1"
    registration: RegistrationContext | None = None

    @model_validator(mode="after")
    def consistent_context(self):
        if self.registration and (
            self.mesh_asset_id != self.registration.mesh_asset_id
            or self.region_id != self.registration.region_id
        ):
            raise ValueError("Mesh and region must match the registered transform")
        return self


class SimulationConfig(Contract):
    contract_version: Literal["1.0"] = "1.0"
    model_id: Literal["local-compartment-chain-v1", "male-cns-hybrid-v1"] = (
        "local-compartment-chain-v1"
    )
    stimulus_region: (
        Literal[
            "head",
            "thorax",
            "abdomen",
            "front_left",
            "front_right",
            "middle_left",
            "middle_right",
            "hind_left",
            "hind_right",
        ]
        | None
    ) = None
    stimulus: Literal["none", "weak", "strong"] = "weak"
    seed: int = Field(default=1, strict=True, ge=0, le=2**31 - 1)
    duration_ms: Finite = Field(default=200, ge=100, le=1000)
    dt_ms: Literal[0.025, 0.0125] = 0.025
    excitability: Finite = Field(default=1.0, ge=0.7, le=1.3)
    adaptation: Finite = Field(default=0.3, ge=0, le=1)
    noise_uv: Finite = Field(default=0.05, ge=0, le=10)
    conductivity_s_m: Finite = Field(default=0.3, ge=0.05, le=2)
    placement: Placement = Field(default_factory=Placement)

    @model_validator(mode="after")
    def distinct_contacts(self):
        if self.model_id == "male-cns-hybrid-v1":
            if self.stimulus_region == "abdomen":
                raise ValueError("No registered tactile population for abdominal stimulation")
            if self.stimulus_region is None or not self.duration_ms.is_integer():
                raise ValueError(
                    "Whole-CNS model requires a region and integer millisecond duration"
                )
        elif self.stimulus_region is not None:
            raise ValueError("Whole-body input regions require the registered whole-CNS model")
        if self.placement.electrode.xyz() == self.placement.reference.xyz():
            raise ValueError("E1 and REF must be distinct")
        return self

    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def dynamics_digest(self) -> str:
        payload = self.model_dump(exclude={"placement", "conductivity_s_m", "noise_uv"})
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class ExecutionRequest(Contract):
    execution_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    config: SimulationConfig
