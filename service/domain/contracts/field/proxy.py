"""Path-free inputs for the experimental whole-network field proxy."""

import hashlib
import json
import math
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from service.contracts import Contract, Finite


class FieldProxyConfig(Contract):
    graph_manifest_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    coordinate_frame: Literal['male-cns-v1.0-native-um']
    source_um: tuple[Finite, Finite, Finite]
    return_um: tuple[Finite, Finite, Finite]
    current_na: Finite
    conductivity_s_m: Finite = Field(gt=0)
    clearance_um: Finite = Field(gt=0)
    gain: Finite
    seed: int = Field(strict=True, ge=0, le=2**31 - 1)
    waveform: list[Finite] = Field(min_length=1, max_length=1000)
    allow_partial_geometry: bool = Field(strict=True)
    allow_missing_curvature: bool = Field(strict=True)
    allow_contact_exclusion: bool = Field(default=False, strict=True)

    @model_validator(mode='after')
    def valid_contacts(self):
        distance = math.dist(self.source_um, self.return_um)
        if not math.isfinite(distance) or distance <= 2 * self.clearance_um:
            raise ValueError('STIM contact exclusion spheres must not overlap')
        if any(abs(value) > 1 for value in self.waveform):
            raise ValueError('Waveform fractions must be between -1 and 1')
        return self

    def field_configuration(self):
        return {'source_um': list(self.source_um), 'return_um': list(self.return_um),
                'current_na': self.current_na, 'conductivity_s_m': self.conductivity_s_m,
                'clearance_um': self.clearance_um}

    def digest(self):
        data = json.dumps(self.model_dump(mode='json'), sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf8')
        return hashlib.sha256(data).hexdigest()


class FieldProxyExecutionRequest(Contract):
    execution_id: UUID
    config: FieldProxyConfig


def from_fragment_population(population, *, gain, allow_partial_geometry,
                             allow_missing_curvature, allow_contact_exclusion):
    """Derive the coarse stimulus from the same saved physical experiment.

    The explicit gain remains uncalibrated; bin averaging does not preserve
    sub-millisecond dynamics. Electrode recording is not generated here.
    """
    from service.domain.contracts.population.fragment import FragmentPopulationConfig

    if not isinstance(population, FragmentPopulationConfig):
        raise ValueError('Validated fragment population required')
    return from_simulation(
        population.simulation, graph_manifest_sha256=population.graph_manifest_sha256,
        seed=population.seed, gain=gain, allow_partial_geometry=allow_partial_geometry,
        allow_missing_curvature=allow_missing_curvature,
        allow_contact_exclusion=allow_contact_exclusion,
    )


def from_simulation(simulation, *, graph_manifest_sha256, seed, gain, allow_partial_geometry,
                    allow_missing_curvature, allow_contact_exclusion):
    """Derive a network-only run without claiming a physical recording was computed."""
    from service.domain.contracts.replay import ReplaySimulation
    from service.domain.pulse_train import pulse_train_millisecond_means

    if not isinstance(simulation, ReplaySimulation):
        raise ValueError('Validated simulation required')
    waveform = pulse_train_millisecond_means(
        start_ms=simulation.pulse_start_ms, end_ms=simulation.pulse_end_ms,
        rise_ms=simulation.rise_time_ms, interphase_gap_ms=simulation.interphase_gap_ms,
        shape=simulation.pulse_shape, duration_ms=simulation.duration_ms,
        count=simulation.pulse_count or 1, interval_ms=simulation.pulse_interval_ms,
    )
    if simulation.current_na != 0 and all(abs(value) <= 1e-12 for value in waveform):
        raise ValueError('Pulse is unresolved at the network time step')
    return FieldProxyConfig.model_validate({
        'graph_manifest_sha256': graph_manifest_sha256,
        'coordinate_frame': simulation.coordinate_frame,
        'source_um': simulation.source_um, 'return_um': simulation.return_um,
        'current_na': simulation.current_na, 'conductivity_s_m': simulation.conductivity_s_m,
        'clearance_um': simulation.clearance_um, 'seed': seed,
        'waveform': waveform, 'gain': gain, 'allow_partial_geometry': allow_partial_geometry,
        'allow_missing_curvature': allow_missing_curvature,
        'allow_contact_exclusion': allow_contact_exclusion,
    })
