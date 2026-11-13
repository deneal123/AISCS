"""Experimental Kirchhoff reduction of extracellular drive at cable junctions.

The calculation uses supplied half-segment resistances in MΩ and potentials
in mV. It is not a tissue model, neuron activation detector, or a substitute
for validating the complete numerical solver and recording operator.
"""

from __future__ import annotations

import math

import numpy as np


def adaptive_junctions(edges, counts, sections, segments, *,
                       segment_resistances=None, child_resistances=None):
    """Describe junctions for ordered SWC edges with individual segment counts.

    Within one section ``ri()`` is the full resistance between adjacent
    segment centres. Splitting that resistance equally across the artificial
    two-way junction preserves its conductance without inventing a branch.
    Section endpoints retain the resistances returned by NEURON itself.
    """
    if ((segment_resistances is None) != (child_resistances is None)
            or (segment_resistances is not None
                and (len(segment_resistances) != len(segments)
                     or len(child_resistances) != len(edges)))):
        raise ValueError('Invalid precomputed cable resistances')
    junctions = {}
    offset = 0
    for edge_index, (node, parent) in enumerate(edges):
        count = counts[node]
        start_resistance = (segments[offset].ri() if segment_resistances is None
                            else segment_resistances[offset])
        junctions.setdefault(('node', parent), []).append((offset, start_resistance))
        for index in range(1, count):
            left, right = offset + index - 1, offset + index
            half_resistance = (segments[right].ri() if segment_resistances is None
                               else segment_resistances[right]) / 2
            junctions[('internal', node, index)] = [
                (left, half_resistance), (right, half_resistance),
            ]
        end_resistance = (sections[node](1).ri() if child_resistances is None
                          else child_resistances[edge_index])
        junctions.setdefault(('node', node), []).append((offset + count - 1, end_resistance))
        offset += count
    if offset != len(segments):
        raise ValueError('Segment count does not match SWC edges')
    return list(junctions.values())


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
    # Counts are updated one endpoint at a time; Python integers avoid a
    # NumPy scalar read/write for every endpoint in large morphologies.
    counts = [0] * len(field)
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
        for index in indices:
            counts[index] += 1
        if len(indices) == 1:
            continue
        if len(indices) == 2:
            first, second = indices
            first_g, second_g = conductances
            total = first_g + second_g
            if not math.isfinite(total) or total <= 0:
                raise ValueError('Invalid junction conductance')
            junction_voltage = (field[first] * first_g + field[second] * second_g) / total
            current[first] += first_g * (junction_voltage - field[first])
            current[second] += second_g * (junction_voltage - field[second])
            continue
        conductance = np.asarray(conductances, dtype=np.float64)
        total = conductance.sum()
        if not np.isfinite(total) or total <= 0:
            raise ValueError('Invalid junction conductance')
        junction_voltage = np.dot(field[indices], conductance) / total
        current[indices] += conductance * (junction_voltage - field[indices])
    if any(count != 2 for count in counts) or not np.isfinite(current).all():
        raise ValueError('Incomplete cable endpoints or non-finite current')
    return current
