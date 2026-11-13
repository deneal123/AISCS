"""Fail-closed correspondence between tagged SWC edges and Arbor probes.

Arbor's voltage and current metadata can contain different numbers of cables:
zero-length fork volumes may appear in one and not the other.  Match geometry
explicitly instead of assuming that their array indices agree.
"""

from __future__ import annotations

import math
from numbers import Real

import numpy as np


def map_edge_volumes(arbor, cell, edge_ids):
    """Resolve uniquely tagged edges to complete, distinct control volumes.

    Requires a separately constructed and authenticated morphology in which
    every requested SWC edge has its own tag. No spatial registration or
    biological identity is inferred by this correspondence.
    """
    raw_ids = list(edge_ids)
    if (not raw_ids or any(isinstance(value, bool | np.bool_)
                           or not isinstance(value, int | np.integer) or not 0 < value < 2**31
                           for value in raw_ids)):
        raise ValueError('Invalid tagged edge IDs')
    ids = [int(value) for value in raw_ids]
    if len(set(ids)) != len(ids):
        raise ValueError('Invalid tagged edge IDs')
    cv = arbor.cv_data(cell)
    if cv is None or type(cv.num_cv) is not int or cv.num_cv < 1:
        raise ValueError('Explicit control-volume discretization required')
    mapped = []
    for node in ids:
        intersections = arbor.intersect_region(f'(tag {node})', cv, 'area')
        positive = []
        for index, proportion in intersections:
            if (type(index) is not int or not 0 <= index < cv.num_cv
                    or isinstance(proportion, bool | np.bool_)
                    or not isinstance(proportion, Real) or not math.isfinite(proportion)
                    or proportion < 0 or proportion > 1 + 1e-9):
                raise ValueError('Invalid control-volume intersection')
            if proportion > 1e-9:
                positive.append((index, proportion))
        if len(positive) != 1 or abs(positive[0][1] - 1) > 1e-9:
            raise ValueError(f'Edge {node} does not map to one complete volume')
        mapped.append(positive[0][0])
    if len(set(mapped)) != len(mapped):
        raise ValueError('Different edges map to the same volume')
    return cv, np.asarray(mapped, dtype=np.int64)


def _cable_key(cable):
    try:
        branch, proximal, distal = cable.branch, cable.prox, cable.dist
    except AttributeError as exc:
        raise ValueError('Invalid probe cable') from exc
    if (type(branch) is not int or branch < 0
            or isinstance(proximal, bool | np.bool_) or isinstance(distal, bool | np.bool_)
            or not isinstance(proximal, Real) or not isinstance(distal, Real)
            or not math.isfinite(proximal) or not math.isfinite(distal)
            or not 0 <= proximal <= distal <= 1):
        raise ValueError('Invalid probe cable')
    return branch, float(proximal), float(distal)


def map_probe_columns(cv, edge_volumes, metadata):
    """Map each edge volume to its vector-probe column, excluding time.

    Matching is exact on Arbor cable coordinates; ambiguous or missing
    matches are errors. Trivial zero-length fork cables are ignored. This
    function does not infer any current or voltage temporal alignment.
    """
    indexes = list(edge_volumes)
    if (not indexes or any(isinstance(index, bool | np.bool_)
                           or not isinstance(index, int | np.integer)
                           or not 0 <= index < cv.num_cv for index in indexes)
            or len(set(indexes)) != len(indexes)):
        raise ValueError('Invalid edge-volume mapping')
    cable_columns = {}
    for position, cable in enumerate(metadata):
        key = _cable_key(cable)
        if key[1] == key[2]:
            continue
        if key in cable_columns:
            raise ValueError('Ambiguous probe metadata')
        cable_columns[key] = position
    result = []
    for index in indexes:
        cables = [_cable_key(cable) for cable in cv.cables(int(index))]
        cables = [key for key in cables if key[1] != key[2]]
        if len(cables) != 1 or cables[0] not in cable_columns:
            raise ValueError('Control volume missing or ambiguous in probe metadata')
        result.append(cable_columns[cables[0]])
    if len(set(result)) != len(result):
        raise ValueError('Probe columns are not unique')
    return np.asarray(result, dtype=np.int64)
