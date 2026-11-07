"""Isolated NEURON reference for a straight cable exposed to an ideal field.

This numerical benchmark is not a Drosophila neuron or a whole-CNS model.
Run in a dedicated process: NEURON's solver and clock are process-global.
"""

from __future__ import annotations

import math

import numpy as np

from .point_field import bipolar_potential_mv, validate_segment_clearance


def simulate_reference_cable(
    source_um,
    return_um,
    current_na: float,
    conductivity_s_m: float,
    *,
    clearance_um: float,
    length_um: float = 200,
    diameter_um: float = 1,
    nseg: int = 51,
    dt_ms: float = 0.025,
    duration_ms: float = 20,
    pulse_start_ms: float = 5,
    pulse_end_ms: float = 6,
) -> dict:
    """Solve a uniform HH cable with segment-specific extracellular potentials.

    Cable axis is X and its midpoint is the coordinate origin. The rectangular
    pulse supplies equal and opposite currents to source and return. Currents
    are net membrane currents in nA, not LIF spikes or current density.
    """
    from neuron import h

    scalars = (length_um, diameter_um, dt_ms, duration_ms, pulse_start_ms, pulse_end_ms)
    if any(isinstance(value, bool | np.bool_) or not math.isfinite(value) for value in scalars):
        raise ValueError("Cable and timing parameters must be finite numbers")
    if (length_um <= 0 or diameter_um <= 0 or dt_ms <= 0 or duration_ms <= 0
            or not 0 < pulse_start_ms < pulse_end_ms < duration_ms):
        raise ValueError("Invalid cable geometry or pulse timing")
    if type(nseg) is not int or nseg < 3 or nseg % 2 == 0:
        raise ValueError("nseg must be an odd integer of at least three")
    if abs(round(duration_ms / dt_ms) * dt_ms - duration_ms) > 1e-9:
        raise ValueError("Duration must be an integer number of steps")
    if any(True for _ in h.allsec()):
        raise RuntimeError("Reference cable requires a dedicated NEURON process")

    points = np.column_stack((
        (np.arange(nseg) + 0.5) * length_um / nseg - length_um / 2,
        np.zeros(nseg), np.zeros(nseg),
    ))
    validate_segment_clearance(
        np.array([[-length_um / 2, 0, 0]]), np.array([[length_um / 2, 0, 0]]),
        [source_um, return_um], clearance_um, np.array([[diameter_um / 2, diameter_um / 2]]),
    )
    potential = bipolar_potential_mv(points, source_um, return_um, current_na,
                                     conductivity_s_m, clearance_um=clearance_um)
    h.load_file("stdrun.hoc")
    h.CVode().active(0)
    h.CVode().use_fast_imem(1)
    cable = h.Section(name="aiscs_reference_cable")
    vectors = []
    try:
        cable.L, cable.diam, cable.nseg = length_um, diameter_um, nseg
        cable.Ra, cable.cm = 100, 1
        cable.insert("hh")
        cable.insert("extracellular")
        times = h.Vector([0, pulse_start_ms, pulse_start_ms, pulse_end_ms,
                          pulse_end_ms, duration_ms])
        segments = list(cable)
        for segment, value in zip(segments, potential, strict=True):
            waveform = h.Vector([0, 0, value, value, 0, 0])
            waveform.play(segment._ref_e_extracellular, times, 1)
            vectors.append(waveform)
        recorded_time = h.Vector().record(h._ref_t)
        voltage = [h.Vector().record(segment._ref_v) for segment in segments]
        membrane_current = [h.Vector().record(segment._ref_i_membrane_) for segment in segments]
        extracellular = [h.Vector().record(segment._ref_vext[0]) for segment in segments]
        h.dt, h.steps_per_ms, h.celsius = dt_ms, 1 / dt_ms, 23
        h.finitialize(-65)
        for _ in range(round(duration_ms / dt_ms)):
            h.fadvance()
        result = {
            "time_ms": np.asarray(recorded_time).copy(),
            "position_um": points,
            "field_mv": potential,
            "voltage_mv": np.asarray([np.asarray(row).copy() for row in voltage]),
            "membrane_current_na": np.asarray([np.asarray(row).copy() for row in membrane_current]),
            "extracellular_mv": np.asarray([np.asarray(row).copy() for row in extracellular]),
        }
        if not all(np.isfinite(value).all() for value in result.values()):
            raise ValueError("Non-finite reference solution")
        return result
    finally:
        for waveform in vectors:
            waveform.play_remove()
        h.delete_section(sec=cable)
