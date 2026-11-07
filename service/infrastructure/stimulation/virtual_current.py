"""Experimental Kirchhoff reduction of extracellular drive at cable junctions.

The calculation uses supplied half-segment resistances in MΩ and potentials
in mV. It is not a tissue model, neuron activation detector, or a substitute
for validating the complete numerical solver and recording operator.
"""

from __future__ import annotations

import math

import numpy as np


def junction_currents(field_mv, junctions):
    """Return inward nA per segment for zero-area, resistive junctions.

    Each junction contains (segment index, endpoint resistance in MΩ) pairs.
    Every segment must appear exactly twice, once at each endpoint. Terminal
    junctions contribute zero, and multiple sections may meet at a junction.
    """
    field = np.asarray(field_mv, dtype=np.float64)
    if field.ndim != 1 or not len(field) or not np.isfinite(field).all():
        raise ValueError('Invalid extracellular potentials')
    if not isinstance(junctions, list | tuple) or not junctions:
        raise ValueError('Invalid cable junctions')
    current = np.zeros(len(field), dtype=np.float64)
    counts = np.zeros(len(field), dtype=np.int64)
    for junction in junctions:
        if not isinstance(junction, list | tuple) or not junction:
            raise ValueError('Empty cable junction')
        indices, conductances = [], []
        for item in junction:
            if not isinstance(item, list | tuple) or len(item) != 2:
                raise ValueError('Invalid cable endpoint')
            index, resistance = item
            if (type(index) is not int or not 0 <= index < len(field)
                    or isinstance(resistance, bool | np.bool_)
                    or not isinstance(resistance, int | float | np.floating)
                    or not math.isfinite(resistance) or resistance <= 0):
                raise ValueError('Invalid cable endpoint')
            indices.append(index)
            conductances.append(1. / resistance)
        if len(set(indices)) != len(indices):
            raise ValueError('Duplicate segment endpoint in junction')
        counts[indices] += 1
        if len(indices) == 1:
            continue
        conductance = np.asarray(conductances, dtype=np.float64)
        total = conductance.sum()
        if not np.isfinite(total) or total <= 0:
            raise ValueError('Invalid junction conductance')
        junction_voltage = np.dot(field[indices], conductance) / total
        current[indices] += conductance * (junction_voltage - field[indices])
    if np.any(counts != 2) or not np.isfinite(current).all():
        raise ValueError('Incomplete cable endpoints or non-finite current')
    return current
