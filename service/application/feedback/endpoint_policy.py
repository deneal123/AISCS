"""Explicit, audited relocation of feedback contacts recorded at cable endpoints.

A GPU replay places a synaptic event inside a finite segment. A contact recorded
exactly at an SWC section endpoint has no finite segment there, so the replay must
receive an interior position on a stated grid. This module performs only that
deterministic relocation and reports what it moved. It selects no tolerance,
claims no physiological validity and runs no solver.

Admission is checked without reading a morphology again: a feedback contact is
already bounded by the source and target centreline limits of the matching step,
and the farthest point of a finite segment lies on the same straight edge, so

    distance(observation, segment centre) <= max_target_distance_um + max_shift_um

with max_shift_um = edge_length / (2 * count). Callers that need a tighter bound
than that must raise their own limits, or verify the geometry per cell with
audit_relocation.
"""

from __future__ import annotations

import math

POSITIONS = (0, 1)


def endpoint_position(position, count):
    """Interior position of the outermost finite segment on the recorded side."""
    if (type(count) is not int or count < 1 or count % 2 != 1
            or isinstance(position, bool) or not isinstance(position, int | float)
            or position not in POSITIONS):
        raise ValueError("Invalid endpoint relocation request")
    return .5 / count if position == 0 else 1 - .5 / count


def admission_bound(max_target_distance_um, max_shift_um):
    """Largest observation-to-centre distance the matching limits already imply."""
    numbers = (max_target_distance_um, max_shift_um)
    if any(isinstance(value, bool) or not isinstance(value, int | float)
           or not math.isfinite(value) or value < 0 for value in numbers):
        raise ValueError("Invalid admission limits")
    return float(max_target_distance_um) + float(max_shift_um)


def structural_count(swc, *, max_shift_um, max_nseg):
    """Smallest odd segments-per-edge that bounds the shift on the longest edge.

    The grid then follows the morphology alone, so it does not change while the
    feedback schedule evolves. Subdividing adds segments to the solver, so this is
    offered for callers that accept that cost; the default policy keeps one
    segment per edge and states the resulting shift instead.
    """
    if (isinstance(max_shift_um, bool) or not isinstance(max_shift_um, int | float)
            or not math.isfinite(max_shift_um) or max_shift_um <= 0
            or type(max_nseg) is not int or max_nseg < 1 or max_nseg % 2 != 1):
        raise ValueError("Invalid structural grid limits")
    nodes = {}
    for line in swc.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        row = line.split()
        nodes[int(row[0])] = ([float(value) * .008 for value in row[2:5]], int(row[6]))
    longest = 0.
    for point, parent in nodes.values():
        if parent == -1:
            continue
        length = math.dist(point, nodes[parent][0])
        if math.isfinite(length) and length > longest:
            longest = length
    if longest <= 0:
        raise ValueError("Feedback target morphology has no measurable edge")
    count = 1
    while count < max_nseg and longest / (2 * count) > max_shift_um:
        count += 2
    if longest / (2 * count) > max_shift_um:
        raise ValueError("Feedback target morphology exceeds the structural grid limit")
    return count


def relocate_endpoints(schedule, counts=None):
    """Replace recorded endpoint contacts with interior positions of their grid.

    "counts" maps body id to segments-per-edge and defaults to one segment per
    edge, which is the grid a cached one-segment replay already uses. The walk is
    deterministic and touches no morphology, so the digest can be recomputed per
    iteration at negligible cost. A schedule without endpoint contacts is returned
    unchanged, byte for byte, so its digest is preserved.
    """
    from service.application.feedback.fixed_inputs import fixed_input_digest

    if (not isinstance(schedule, dict)
            or not isinstance(schedule.get("events_by_target"), dict)
            or (counts is not None and not isinstance(counts, dict))):
        raise ValueError("Invalid endpoint relocation inputs")
    counts = {} if counts is None else counts
    relocated = dict(schedule)
    events_by_target = {}
    moved = 0
    grids = {}
    for body, events in schedule["events_by_target"].items():
        if not isinstance(body, int) or not isinstance(events, list):
            raise ValueError("Invalid feedback event list")
        count = counts.get(body, 1)
        if type(count) is not int or count < 1 or count % 2 != 1:
            raise ValueError("Invalid feedback target grid")
        rows = []
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("Invalid feedback event")
            position = event.get("position")
            if position is None:
                # No position at all: not a recorded endpoint. The solver rejects
                # such an event on its own terms; this function only relocates.
                rows.append(event)
                continue
            if (isinstance(position, bool) or not isinstance(position, int | float)
                    or not math.isfinite(position) or not 0 <= position <= 1):
                raise ValueError("Invalid feedback event position")
            if position in POSITIONS:
                rows.append({**event, "position": endpoint_position(position, count)})
                moved += 1
                grids[body] = count
            else:
                rows.append(event)
        events_by_target[body] = rows
    if not moved:
        return {"schedule": schedule, "sha256": fixed_input_digest(schedule), "audit": None}
    relocated["events_by_target"] = events_by_target
    relocated["endpoint_relocation"] = {
        "relocated": moved,
        "cells": len(grids),
        "max_nseg": max(grids.values(), default=1),
        "rule": "an endpoint contact is placed at the centre of the outermost finite "
                "segment of its own SWC edge, so its displacement is at most half that "
                "edge length, and a contact observed within max_target_distance_um of "
                "the centreline is then at most max_target_distance_um plus half the "
                "edge length from the segment centre",
        "interpretation": "deterministic geometric relocation; not numerical or "
                          "biological validation",
    }
    return {"schedule": relocated, "sha256": fixed_input_digest(relocated),
            "audit": relocated["endpoint_relocation"]}
