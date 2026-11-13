"""Fast in-process prepare stage for the ASPA generator's GPU cable solver.

This module replaces the NEURON-based prepare_cached_cell path with a
NEURON-free computation that reproduces that path's results:

* cable area and axial resistances follow the validated pure-numpy NEURON
  replica (cable-replica-20261110.py), including the float32 round-trip of
  pt3d coordinates and radii;
* Kirchhoff junction reduction follows virtual_current.adaptive_junctions and
  virtual_current.junction_currents exactly, including junction membership
  order (the dict insertion order of the reference implementation);
* the Hines tree (parents, conductances, segment_nodes) follows
  experimental_gpu.tree_geometry.refined_tree exactly: its BFS order, its
  virtual-node numbering, its adjacency insertion order and its
  multi-component (forest) root rule;
* the field follows point_field.bipolar_potential_mv and the per-segment
  clearance predicate follows point_field.validate_segment_clearance.

All per-segment arithmetic runs inside one numba kernel with prange over cells,
so a chunk of cells costs one C call and zero per-cell Python work. Chunk reads
(file read + SHA-256 + zlib inflate) are overlapped with compute by a bounded
producer/consumer pipeline.

Public API
----------
Params                    immutable per-run physical parameters
PreparedChunk             flat GPU-ready arrays for a chunk of cells
prepare_chunk             prepare one already-decoded chunk
prepare_batch             prepare several decoded chunks in one kernel call
iter_decoded_chunks       bounded parallel reader (read + sha256 + inflate)
iter_prepared_chunks      fused reader + compute pipeline
prepare_cache             whole-cache iterator
read_chunk_file           verified single-chunk read
load_manifest             read and check a cache manifest

The chunk record dtype is geometry_cache.chunk._RECORD.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import re
import threading
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Point numba's on-disk cache beside this module unless the caller chose one.
# Import-time only, so it has to precede the numba import.
os.environ.setdefault(
    "NUMBA_CACHE_DIR", str(Path(__file__).resolve().parent / ".numba-cache")
)

from numba import get_num_threads, njit, prange, set_num_threads  # noqa: E402

__all__ = [
    "CACHE_RECORD",
    "HH_INITIAL_GATES",
    "HH_INITIAL_VOLTAGE_MV",
    "Params",
    "PreparedChunk",
    "PrepareError",
    "iter_decoded_chunks",
    "iter_prepared_chunks",
    "load_manifest",
    "prepare_batch",
    "prepare_cache",
    "prepare_chunk",
    "prepare_descriptor_chunk",
    "read_chunk_file",
    "set_num_threads",
    "get_num_threads",
]

# ---------------------------------------------------------------------------
# Record format (geometry_cache.chunk._RECORD) and reference constants
# ---------------------------------------------------------------------------

CACHE_RECORD = np.dtype(
    [
        ("x", "<f8"),
        ("y", "<f8"),
        ("z", "<f8"),
        ("radius", "<f8"),
        ("parent", "<i4"),
        ("id", "<i4"),
    ]
)

RECORD_ITEMSIZE = 40
MAX_VERTICES = 1_000_000
CHUNK_FORMAT = "malecns-packed-geometry-chunk-v1"

# NEURON hh rates at -65 mV and 23 degC, as returned by
# experimental_gpu.hh_table.prepare_hh_table() (minf, hinf, ninf). They do not
# depend on morphology, so the fast path broadcasts them; see REPORT.md.
HH_INITIAL_GATES = np.array(
    [0.05293248525724958, 0.5961207535084603, 0.3176769140606974], dtype=np.float64
)
HH_INITIAL_VOLTAGE_MV = -65.0

# Error codes mirror the reference path's failure semantics one for one.
_MESSAGES = {
    1: "Invalid cable edges",
    2: "Invalid cable node",
    3: "Invalid cable resistance",
    4: "Cable graph contains a cycle",
    5: "Disconnected component has no segment",
    6: "Disconnected cable graph",
    7: "Invalid cable coordinates or radii",
    8: "Contact exclusion sphere intersects a cable segment",
    9: "Observation point intersects a contact exclusion sphere",
    10: "Invalid prepared cell",
    11: "Contact exclusion spheres must not intersect",
    12: "Cached geometry has no root",
    13: "Segments must have finite nonzero lengths",
    14: "Junction membership beyond the bit-exact reduction range",
    15: "Invalid junction conductance",
    16: "Incomplete cable endpoints or non-finite current",
}

# Junction membership has to stay inside the range where the local reductions
# below reproduce numpy bit for bit. Real cable junctions join a handful of
# segments; the check harness reports the observed maximum over the cache.
JUNCTION_LIMIT = 64


class PrepareError(ValueError):
    """Raised where the reference path raises: invalid or unusable geometry."""


@dataclass(frozen=True)
class Params:
    """Physical parameters of one prepare run.

    nseg is the uniform, odd number of segments per SWC edge. The cached
    reference path used 1, which is also the default here.
    """

    source_um: tuple
    return_um: tuple
    current_na: float
    conductivity_s_m: float
    clearance_um: float
    axial_resistivity: float = 100.0
    capacitance: float = 1.0
    nseg: int = 1

    def checked(self):
        """Validate once, before any chunk is touched."""
        try:
            source = tuple(float(v) for v in self.source_um)
            ret = tuple(float(v) for v in self.return_um)
        except (TypeError, ValueError) as exc:
            raise ValueError("Contacts must be three numbers each") from exc
        if len(source) != 3 or len(ret) != 3:
            raise ValueError("Contacts must be three numbers each")
        if not all(math.isfinite(v) for v in source + ret):
            raise ValueError("Contacts must be finite")
        for name in (
            "current_na",
            "conductivity_s_m",
            "clearance_um",
            "axial_resistivity",
            "capacitance",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(name + " must be a number")
            if not math.isfinite(value):
                raise ValueError(name + " must be finite")
        if self.conductivity_s_m <= 0.0:
            raise ValueError("Conductivity must be positive")
        if self.clearance_um <= 0.0:
            raise ValueError("Clearance must be positive")
        if self.axial_resistivity <= 0.0:
            raise ValueError("Axial resistivity must be positive")
        if self.capacitance <= 0.0:
            raise ValueError("Capacitance must be positive")
        if type(self.nseg) is not int or self.nseg < 1 or self.nseg % 2 != 1:
            raise ValueError("Segment counts must be positive and odd")
        dx = source[0] - ret[0]
        dy = source[1] - ret[1]
        dz = source[2] - ret[2]
        distance = math.sqrt((dx * dx + dy * dy) + dz * dz)
        if not math.isfinite(distance):
            raise ValueError("Contact distance overflow")
        if distance <= 2.0 * self.clearance_um:
            raise PrepareError(_MESSAGES[11])
        return self


# ---------------------------------------------------------------------------
# Inline helpers. fastmath stays off everywhere: the contract is parity with
# the reference path, not speed bought with rounding.
# ---------------------------------------------------------------------------


@njit(cache=True, inline="always", fastmath=False)
def _f32(value):
    """Round a float64 through float32, as NEURON's pt3d arrays do."""
    return np.float64(np.float32(value))


@njit(cache=True, inline="always", fastmath=False)
def _norm3(dx, dy, dz):
    """np.linalg.norm(axis=1) for one row: left-associated squares."""
    return math.sqrt((dx * dx + dy * dy) + dz * dz)


@njit(cache=True, inline="always", fastmath=False)
def _antiderivative(x, linear, r0, k, inv):
    """Antiderivative of 1/(pi r(x)^2) behind the validated cable replica."""
    if linear:
        return x / (r0 * r0)
    return (-inv) / (r0 + k * x)


@njit(cache=True, inline="always", fastmath=False)
def _dot3(ax, ay, az, bx, by, bz):
    """np.einsum('ij,ij->i', ...) for one row of three components."""
    return ((ax * bx + ay * by) + az * bz)


@njit(cache=True, inline="always", fastmath=False)
def _dot_range(a, alo, b, blo, n):
    """Left-to-right dot product, the order numpy.dot uses on short vectors."""
    total = 0.0
    for offset in range(n):
        total += a[alo + offset] * b[blo + offset]
    return total


@njit(cache=True, fastmath=False)
def _sum_range(values, lo, hi):
    """numpy.sum order over values[lo:hi]: 8 lanes for 8 <= n <= 128."""
    n = hi - lo
    if n < 8:
        total = 0.0
        for index in range(lo, hi):
            total += values[index]
        return total
    if n > 128:
        return math.nan
    acc0 = values[lo]
    acc1 = values[lo + 1]
    acc2 = values[lo + 2]
    acc3 = values[lo + 3]
    acc4 = values[lo + 4]
    acc5 = values[lo + 5]
    acc6 = values[lo + 6]
    acc7 = values[lo + 7]
    index = lo + 8
    limit = hi - (n % 8)
    while index < limit:
        acc0 += values[index]
        acc1 += values[index + 1]
        acc2 += values[index + 2]
        acc3 += values[index + 3]
        acc4 += values[index + 4]
        acc5 += values[index + 5]
        acc6 += values[index + 6]
        acc7 += values[index + 7]
        index += 8
    total = ((acc0 + acc1) + (acc2 + acc3)) + ((acc4 + acc5) + (acc6 + acc7))
    while index < hi:
        total += values[index]
        index += 1
    return total


@njit(cache=True, inline="always", fastmath=False)
def _dot_junction(field, seg, conductance, lo, n):
    """np.dot(field[indices], conductance) with indices in junction order."""
    total = 0.0
    for offset in range(n):
        total += field[seg[lo + offset]] * conductance[lo + offset]
    return total


# ---------------------------------------------------------------------------
# The prepare kernel: one prange over every cell of a batch of chunks
# ---------------------------------------------------------------------------


@njit(cache=True, parallel=True, boundscheck=False, fastmath=False, nogil=True)
def _prepare_kernel(
    rows,
    order,
    chunk_of_cell,
    cell_start,
    cell_count,
    seg_base,
    node_base,
    junc_base,
    ns,
    ra,
    source,
    ret,
    current_na,
    sigma,
    clearance,
    store_bounds,
    area_out,
    starts_out,
    ends_out,
    mid_out,
    field_out,
    fcur_out,
    parents_out,
    cond_out,
    segnode_out,
    segid_out,
    segindex_out,
    pres_out,
    cres_out,
    edgerow_out,
    joff_out,
    jseg_out,
    jcond_out,
    jvolt_out,
    cell_edges,
    cell_segments,
    cell_nodes,
    cell_junctions,
    cell_roots,
    cell_members,
    err_out,
    cell_out,
):
    """Prepare every cell of a batch in one pass.

    Each cell runs the reference call chain in order: segment clearance, the
    cable replica's area and ri(), refined_tree's adjacency and BFS,
    bipolar_potential_mv at the midpoints, and junction_currents. All scratch
    is per iteration, so cells are independent under prange, and every output
    is addressed through precomputed flat offsets, so the result is identical
    regardless of thread scheduling.
    """
    pcol = rows["parent"]
    idcol = rows["id"]
    xcol = rows["x"]
    ycol = rows["y"]
    zcol = rows["z"]
    rcol = rows["radius"]
    pi = math.pi
    field_factor = current_na / (4.0 * pi * sigma)
    scale = ((ra * 1e4) / pi) / 1e6
    ncell = order.shape[0]

    for slot in prange(ncell):
        cell = order[slot]
        chunk = chunk_of_cell[cell]
        start = cell_start[cell]
        n = cell_count[cell]
        err_out[cell] = 0
        cell_edges[cell] = 0
        cell_segments[cell] = 0
        cell_nodes[cell] = 0
        cell_junctions[cell] = 0
        cell_roots[cell] = 0
        cell_members[cell] = 0
        cell_out[cell] = cell
        if n < 2:
            err_out[cell] = 1
            continue

        # ---- structural scan: edge rows, roots, virtual-vertex numbering ----
        edge_row = np.empty(n, dtype=np.int64)
        vslot = np.full(n, -1, dtype=np.int64)
        n_edges = 0
        n_roots = 0
        n_vertices = 0
        bad = 0
        for row_local in range(n):
            parent_local = pcol[start + row_local]
            if parent_local == -1:
                n_roots += 1
                continue
            if parent_local < -1 or parent_local >= n or parent_local == row_local:
                bad = 2
                break
            edge_row[n_edges] = row_local
            n_edges += 1
        if bad != 0:
            err_out[cell] = bad
            continue
        if n_roots == 0:
            err_out[cell] = 12
            continue
        if n_edges == 0:
            err_out[cell] = 7
            continue
        # refined_tree numbers the vertices of participating rows in edge
        # order: parent first, then child, each at most once.
        for edge_index in range(n_edges):
            row_local = edge_row[edge_index]
            parent_local = pcol[start + row_local]
            if vslot[parent_local] < 0:
                vslot[parent_local] = n_vertices
                n_vertices += 1
            if vslot[row_local] < 0:
                vslot[row_local] = n_vertices
                n_vertices += 1
        seg_total = n_edges * ns
        nodes_v = seg_total + n_vertices
        seg_at = seg_base[cell]
        node_at = node_base[cell]

        pres = np.empty(seg_total, dtype=np.float64)
        cres = np.empty(n_edges, dtype=np.float64)

        # ---- edge pass: clearance predicate, area, axial resistances --------
        clearance_bad = 0
        for edge_index in range(n_edges):
            row_local = edge_row[edge_index]
            parent_local = pcol[start + row_local]
            row = start + row_local
            prow = start + parent_local
            ox = xcol[prow]
            oy = ycol[prow]
            oz = zcol[prow]
            xc64 = xcol[row]
            yc64 = ycol[row]
            zc64 = zcol[row]
            rp64 = rcol[prow]
            rc64 = rcol[row]
            dx64 = xc64 - ox
            dy64 = yc64 - oy
            dz64 = zc64 - oz
            length64 = _norm3(dx64, dy64, dz64)
            if not math.isfinite(length64) or not math.isfinite(rp64) or not math.isfinite(rc64):
                bad = 7
                break
            if length64 <= 0.0 or rp64 <= 0.0 or rc64 <= 0.0:
                bad = 7
                break
            # point_field.validate_segment_clearance, one contact at a time,
            # with the conservative maximum of the two endpoint radii.
            if clearance_bad == 0:
                local_radius = rp64 if rp64 > rc64 else rc64
                for contact_index in range(2):
                    if contact_index == 0:
                        cx = source[0]
                        cy = source[1]
                        cz = source[2]
                    else:
                        cx = ret[0]
                        cy = ret[1]
                        cz = ret[2]
                    wx = cx - ox
                    wy = cy - oy
                    wz = cz - oz
                    denominator = _dot3(dx64, dy64, dz64, dx64, dy64, dz64)
                    if not math.isfinite(denominator) or denominator <= 0.0:
                        bad = 13
                        break
                    fraction = _dot3(wx, wy, wz, dx64, dy64, dz64) / denominator
                    if fraction < 0.0:
                        fraction = 0.0
                    elif fraction > 1.0:
                        fraction = 1.0
                    px = ox + fraction * dx64 - cx
                    py = oy + fraction * dy64 - cy
                    pz = oz + fraction * dz64 - cz
                    if _norm3(px, py, pz) <= clearance + local_radius:
                        clearance_bad = 1
                if bad != 0:
                    break
            # NEURON stores pt3d coordinates and diameters as float32; the
            # validated replica reproduces that round-trip, so this does too.
            xp = _f32(ox)
            yp = _f32(oy)
            zp = _f32(oz)
            xc = _f32(xc64)
            yc = _f32(yc64)
            zc = _f32(zc64)
            rp = _f32(rp64)
            rc = _f32(rc64)
            dx = xc - xp
            dy = yc - yp
            dz = zc - zp
            length = _norm3(dx, dy, dz)
            if not math.isfinite(length) or length <= 0.0:
                bad = 7
                break
            k = (rc - rp) / length
            linear = abs(k) < 1e-15
            kk = 1.0 if linear else k
            inv = 1.0 / kk
            base = edge_index * ns
            for segment in range(ns):
                if segment == 0:
                    a_um = 0.0
                else:
                    a_um = ((segment - 0.5) * length) / ns
                b_um = ((segment + 0.5) * length) / ns
                pres[base + segment] = scale * (
                    _antiderivative(b_um, linear, rp, kk, inv)
                    - _antiderivative(a_um, linear, rp, kk, inv)
                )
                f0 = segment / ns
                f1 = (segment + 1) / ns
                radius0 = rp + f0 * (rc - rp)
                radius1 = rp + f1 * (rc - rp)
                seg_len_um = length / ns
                delta_r = radius1 - radius0
                sx = ox + f0 * dx64
                sy = oy + f0 * dy64
                sz = oz + f0 * dz64
                ex = ox + f1 * dx64
                ey = oy + f1 * dy64
                ez = oz + f1 * dz64
                out = seg_at + base + segment
                area_out[out] = (
                    pi
                    * (radius0 + radius1)
                    * math.sqrt(seg_len_um * seg_len_um + delta_r * delta_r)
                )
                mid_out[out, 0] = (sx + ex) / 2.0
                mid_out[out, 1] = (sy + ey) / 2.0
                mid_out[out, 2] = (sz + ez) / 2.0
                segindex_out[out] = segment
                segid_out[out] = idcol[row]
                if store_bounds != 0:
                    starts_out[out, 0] = sx
                    starts_out[out, 1] = sy
                    starts_out[out, 2] = sz
                    ends_out[out, 0] = ex
                    ends_out[out, 1] = ey
                    ends_out[out, 2] = ez
            cres[edge_index] = scale * (
                _antiderivative(length, linear, rp, kk, inv)
                - _antiderivative(((1.0 - 0.5 / ns) * length), linear, rp, kk, inv)
            )
            edgerow_out[seg_at + edge_index] = row_local
        if bad != 0:
            err_out[cell] = bad
            continue
        if clearance_bad != 0:
            err_out[cell] = 8
            continue
        for edge_index in range(n_edges):
            if not math.isfinite(cres[edge_index]) or cres[edge_index] <= 0.0:
                bad = 3
                break
        if bad == 0:
            for segment in range(seg_total):
                if not math.isfinite(pres[segment]) or pres[segment] <= 0.0:
                    bad = 3
                    break
        if bad != 0:
            err_out[cell] = bad
            continue
        for segment in range(seg_total):
            out = seg_at + segment
            pres_out[out] = pres[segment]
        for edge_index in range(n_edges):
            cres_out[seg_at + edge_index] = cres[edge_index]

        # ---- field at segment midpoints, with observation clearance ---------
        field_bad = 0
        for segment in range(seg_total):
            out = seg_at + segment
            mx = mid_out[out, 0]
            my = mid_out[out, 1]
            mz = mid_out[out, 2]
            first = _norm3(mx - source[0], my - source[1], mz - source[2])
            second = _norm3(mx - ret[0], my - ret[1], mz - ret[2])
            if not math.isfinite(first) or not math.isfinite(second):
                field_bad = 9
                break
            if first <= clearance or second <= clearance:
                field_bad = 9
                break
            value = field_factor * (1.0 / first - 1.0 / second)
            if not math.isfinite(value):
                field_bad = 9
                break
            field_out[out] = value
        if field_bad != 0:
            err_out[cell] = field_bad
            continue;

        # ---- junctions, in the reference dict-insertion order ---------------
        node_junction = np.full(n, -1, dtype=np.int64)
        internal_base = np.full(n_edges, -1, dtype=np.int64)
        junction_count = 0
        for edge_index in range(n_edges):
            row_local = edge_row[edge_index]
            parent_local = pcol[start + row_local]
            if node_junction[parent_local] < 0:
                node_junction[parent_local] = junction_count
                junction_count += 1
            if ns > 1:
                internal_base[edge_index] = junction_count
                junction_count += ns - 1
            if node_junction[row_local] < 0:
                node_junction[row_local] = junction_count
                junction_count += 1
        jj = junc_base[cell]
        jcount = np.zeros(junction_count, dtype=np.int64)
        for edge_index in range(n_edges):
            row_local = edge_row[edge_index]
            parent_local = pcol[start + row_local]
            jcount[node_junction[parent_local]] += 1
            if ns > 1:
                base_junction = internal_base[edge_index]
                for offset in range(ns - 1):
                    jcount[base_junction + offset] += 2
            jcount[node_junction[row_local]] += 1
        running = jj
        for junction in range(junction_count):
            joff_out[jj + junction] = running
            running += jcount[junction]
        joff_out[jj + junction_count] = running
        cursor = np.empty(junction_count, dtype=np.int64)
        for junction in range(junction_count):
            cursor[junction] = joff_out[jj + junction]
        for edge_index in range(n_edges):
            row_local = edge_row[edge_index]
            parent_local = pcol[start + row_local]
            base = seg_at + edge_index * ns
            junction = node_junction[parent_local]
            spot = cursor[junction]
            jseg_out[spot] = base
            jcond_out[spot] = 1.0 / pres[edge_index * ns]
            cursor[junction] = spot + 1
            if ns > 1:
                base_junction = internal_base[edge_index]
                for offset in range(ns - 1):
                    half = pres[edge_index * ns + offset + 1] / 2.0
                    conductance = 1.0 / half
                    spot = cursor[base_junction + offset]
                    jseg_out[spot] = base + offset
                    jcond_out[spot] = conductance
                    jseg_out[spot + 1] = base + offset + 1
                    jcond_out[spot + 1] = conductance
                    cursor[base_junction + offset] = spot + 2
            junction = node_junction[row_local]
            spot = cursor[junction]
            jseg_out[spot] = base + ns - 1
            jcond_out[spot] = 1.0 / cres[edge_index]
            cursor[junction] = spot + 1

        # ---- junction voltages, then segment currents ----------------------
        widest = 0
        for junction in range(junction_count):
            lo = joff_out[jj + junction]
            hi = joff_out[jj + junction + 1]
            members = hi - lo
            if members > widest:
                widest = members
            if members < 2:
                jvolt_out[jj + junction] = 0.0
                continue
            if members == 2:
                first_index = jseg_out[lo]
                second_index = jseg_out[lo + 1]
                first_g = jcond_out[lo]
                second_g = jcond_out[lo + 1]
                total = first_g + second_g
                if not math.isfinite(total) or total <= 0.0:
                    bad = 15
                    break
                voltage = (
                    field_out[first_index] * first_g + field_out[second_index] * second_g
                ) / total
                jvolt_out[jj + junction] = voltage
                fcur_out[first_index] += first_g * (voltage - field_out[first_index])
                fcur_out[second_index] += second_g * (voltage - field_out[second_index])
                continue
            if members > 128:
                bad = 14
                break
            total = _sum_range(jcond_out, lo, hi)
            if not math.isfinite(total) or total <= 0.0:
                bad = 15
                break
            voltage = _dot_junction(field_out, jseg_out, jcond_out, lo, members) / total
            jvolt_out[jj + junction] = voltage
            for spot in range(lo, hi):
                index = jseg_out[spot]
                fcur_out[index] += jcond_out[spot] * (voltage - field_out[index])
        if bad != 0:
            err_out[cell] = bad
            continue
        cell_members[cell] = widest;

        # ---- Hines adjacency, built in refined_tree's link() order ----------
        # refined_tree links, per edge: (parent vertex -> seg0), (seg_i ->
        # seg_i+1), ..., (last seg -> child vertex), appending both directions
        # each time. Degree counting first keeps the fill allocation-free.
        degree = np.zeros(nodes_v, dtype=np.int64)
        for edge_index in range(n_edges):
            row_local = edge_row[edge_index]
            previous = seg_total + vslot[pcol[start + row_local]]
            base = edge_index * ns
            for segment in range(ns):
                degree[previous] += 1
                degree[base + segment] += 1
                previous = base + segment
            degree[previous] += 1
            degree[seg_total + vslot[row_local]] += 1
        adj_off = np.empty(nodes_v + 1, dtype=np.int64)
        running = 0
        for node in range(nodes_v):
            adj_off[node] = running
            running += degree[node]
        adj_off[nodes_v] = running
        adj_node = np.empty(running, dtype=np.int64)
        adj_cond = np.empty(running, dtype=np.float64)
        fill = adj_off[:nodes_v].copy()
        for edge_index in range(n_edges):
            row_local = edge_row[edge_index]
            previous = seg_total + vslot[pcol[start + row_local]]
            base = edge_index * ns
            for segment in range(ns):
                current = base + segment
                conductance = 1.0 / pres[edge_index * ns + segment]
                spot = fill[previous]
                adj_node[spot] = current
                adj_cond[spot] = conductance
                fill[previous] = spot + 1
                spot = fill[current]
                adj_node[spot] = previous
                adj_cond[spot] = conductance
                fill[current] = spot + 1
                previous = current
            child_vertex = seg_total + vslot[row_local]
            conductance = 1.0 / cres[edge_index]
            spot = fill[previous]
            adj_node[spot] = child_vertex
            adj_cond[spot] = conductance
            fill[previous] = spot + 1
            spot = fill[child_vertex]
            adj_node[spot] = previous
            adj_cond[spot] = conductance
            fill[child_vertex] = spot + 1

        # ---- BFS, reproducing refined_tree's order and cycle predicate ------
        bfs_index = np.full(nodes_v, -1, dtype=np.int64)
        order_nodes = np.empty(nodes_v, dtype=np.int64)
        seen = np.zeros(nodes_v, dtype=np.bool_)
        queue = np.empty(nodes_v, dtype=np.int64)
        order_nodes[0] = 0
        bfs_index[0] = 0
        seen[0] = True
        parents_out[node_at] = -1
        cond_out[node_at] = 0.0
        queue[0] = 0
        head = 0
        tail = 1
        count = 1
        next_component = 0
        while head < tail or count < nodes_v:
            if head == tail:
                while next_component < seg_total and seen[next_component]:
                    next_component += 1
                if next_component == seg_total:
                    bad = 5
                    break
                seen[next_component] = True
                bfs_index[next_component] = count
                order_nodes[count] = next_component
                parents_out[node_at + count] = 0
                cond_out[node_at + count] = 0.0
                queue[tail] = count
                tail += 1
                count += 1
                continue
            current = queue[head]
            head += 1
            virtual = order_nodes[current]
            parent_index = parents_out[node_at + current]
            for spot in range(adj_off[virtual], adj_off[virtual + 1]):
                neighbour = adj_node[spot]
                if not seen[neighbour]:
                    seen[neighbour] = True
                    bfs_index[neighbour] = count
                    order_nodes[count] = neighbour
                    parents_out[node_at + count] = current
                    cond_out[node_at + count] = adj_cond[spot]
                    queue[tail] = count
                    tail += 1
                    count += 1
                elif parent_index < 0 or neighbour != order_nodes[parent_index]:
                    bad = 4
                    break
            if bad != 0:
                break
        if bad == 0 and count != nodes_v:
            bad = 6
        if bad != 0:
            err_out[cell] = bad
            continue
        for segment in range(seg_total):
            segnode_out[seg_at + segment] = bfs_index[segment]
        cell_edges[cell] = n_edges
        cell_segments[cell] = seg_total
        cell_nodes[cell] = nodes_v
        cell_junctions[cell] = junction_count
        cell_roots[cell] = n_roots


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreparedChunk:
    """Flat, GPU-ready arrays for every cell of one decoded chunk.

    Per-cell slices are addressed through the *_offsets arrays, so nothing here
    is a Python object per edge or per segment:

    body_ids[i]            SWC id of cell i
    segment_offsets        segment slice of cell i = [segment_offsets[i], segment_offsets[i+1])
    node_offsets           node slice of cell i (Hines tree rows)
    junction_offsets       junction slice of cell i within the chunk junction block
    area                   lateral membrane area, um^2, per segment
    parents                Hines tree parent node per node, -1 at each root
    conductances           axial conductance per node, 0 at roots
    segment_nodes          Hines node index of each segment
    field_mv               extracellular potential at each segment midpoint
    field_current_na       junction drive per segment (the reference
                           field_current_na)
    segment_ids            SWC id owning each segment
    segment_index          index of the segment inside its SWC edge
    edge_rows              cache row index (relative to the chunk) of each
                           edge, in edge order
    parent_resistance      axial resistance between segment centres, MOhm
    child_resistance       axial resistance at the child end of each edge, MOhm
    starts_um, ends_um     segment endpoints, only with store_bounds=True
    junction_offsets ...   junction_offsets, junction_segments,
                           junction_conductances, junction_voltage_mv describe
                           the Kirchhoff junctions in reference insertion order
    error_codes            per-cell reference-style error code, 0 when prepared
    edge_counts, segment_counts, node_counts, junction_counts, component_counts,
    max_junction_members   per-cell graph sizes
    initial_gates          (ncell, 3) minf/hinf/ninf at HH_INITIAL_VOLTAGE_MV
    """

    body_ids: np.ndarray
    segment_offsets: np.ndarray
    node_offsets: np.ndarray
    junction_offsets: np.ndarray
    area: np.ndarray
    parents: np.ndarray
    conductances: np.ndarray
    segment_nodes: np.ndarray
    field_mv: np.ndarray
    field_current_na: np.ndarray
    segment_ids: np.ndarray
    segment_index: np.ndarray
    edge_rows: np.ndarray
    parent_resistance: np.ndarray
    child_resistance: np.ndarray
    starts_um: np.ndarray
    ends_um: np.ndarray
    midpoints_um: np.ndarray
    junction_segments: np.ndarray
    junction_conductances: np.ndarray
    junction_voltage_mv: np.ndarray
    error_codes: np.ndarray
    edge_counts: np.ndarray
    segment_counts: np.ndarray
    node_counts: np.ndarray
    junction_counts: np.ndarray
    component_counts: np.ndarray
    max_junction_members: np.ndarray
    initial_gates: np.ndarray
    params: Params

    @property
    def cells(self):
        return len(self.body_ids)

    @property
    def segments(self):
        return int(self.area.shape[0])

    @property
    def nodes(self):
        return int(self.parents.shape[0])

    def ok(self):
        return bool(np.all(self.error_codes == 0))

    def cell(self, index):
        """Per-cell views without copying: the dict the GPU solver batch needs."""
        s0, s1 = int(self.segment_offsets[index]), int(self.segment_offsets[index + 1])
        n0, n1 = int(self.node_offsets[index]), int(self.node_offsets[index + 1])
        return {
            "id": int(self.body_ids[index]),
            "area": self.area[s0:s1],
            "parents": self.parents[n0:n1],
            "conductances": self.conductances[n0:n1],
            "segment_nodes": self.segment_nodes[s0:s1],
            "field_current_na": self.field_current_na[s0:s1],
            "field_mv": self.field_mv[s0:s1],
            "initial_gates": self.initial_gates[index],
        }

    def as_gpu(self):
        """int32 tree arrays for the CUDA packing path (index range guard)."""
        if self.parents.shape[0] and int(self.parents.max()) >= 2**31 - 1:
            raise PrepareError("Hines node index exceeds int32")
        return {
            "parents": self.parents.astype(np.int32, copy=False),
            "segment_nodes": self.segment_nodes.astype(np.int32, copy=False),
            "conductances": self.conductances,
            "area": self.area,
            "field_current_na": self.field_current_na,
        }


# ---------------------------------------------------------------------------
# Prepare entry points
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Kernel 0: structural sizing (plan columns: 0 start, 1 rows, 2 edges,
# 3 edges-per-cell segment multiplier, 4 non-segment vertices, 8 roots)
# ---------------------------------------------------------------------------


@njit(cache=True, parallel=True, boundscheck=False, fastmath=False, nogil=True)
def _size_kernel(rows, cell_start, cell_count, ns, plan, err_out):
    """Count graph sizes per cell and reject structurally invalid cells."""
    pcol = rows["parent"]
    ncell = cell_start.shape[0]
    for cell in prange(ncell):
        start = cell_start[cell]
        n = cell_count[cell]
        for slot in range(9):
            plan[cell, slot] = 0
        err_out[cell] = 0
        if n < 2:
            err_out[cell] = 1
            continue
        n_edges = 0
        n_roots = 0
        bad = 0
        for row_local in range(n):
            parent_local = pcol[start + row_local]
            if parent_local == -1:
                n_roots += 1
                continue
            if parent_local < -1 or parent_local >= n or parent_local == row_local:
                bad = 2
                break
            n_edges += 1
        if bad != 0:
            err_out[cell] = bad
            continue
        if n_roots == 0:
            err_out[cell] = 12
            continue
        if n_edges == 0:
            err_out[cell] = 7
            continue
        seen = np.zeros(n, dtype=np.bool_)
        for row_local in range(n):
            parent_local = pcol[start + row_local]
            if parent_local != -1:
                seen[parent_local] = True
        n_vertices = 0
        for row_local in range(n):
            if seen[row_local] or pcol[start + row_local] != -1:
                n_vertices += 1
        plan[cell, 0] = start
        plan[cell, 1] = n
        plan[cell, 2] = n_edges
        plan[cell, 3] = n_edges
        plan[cell, 4] = n_vertices
        plan[cell, 8] = n_roots


def _checked_rows(rows):
    if not isinstance(rows, np.ndarray) or rows.dtype != CACHE_RECORD or rows.ndim != 1:
        raise ValueError("Decoded chunk must be a 1-D array of the cache record dtype")
    if not 1 <= rows.shape[0] <= MAX_VERTICES:
        raise ValueError("Decoded chunk vertex count outside the cache format")
    return rows


def _checked_layout(rows, starts, counts, params):
    starts = np.ascontiguousarray(starts, dtype=np.int64)
    counts = np.ascontiguousarray(counts, dtype=np.int64)
    if starts.ndim != 1 or counts.shape != starts.shape or starts.shape[0] < 1:
        raise ValueError("Per-neuron offsets and counts must be matching 1-D arrays")
    if (starts < 0).any() or (counts <= 0).any():
        raise ValueError("Per-neuron offsets must be non-negative and counts positive")
    ends = starts + counts
    if int(ends.max()) > rows.shape[0] or int(starts[0]) != 0:
        raise ValueError("Per-neuron offsets must tile the decoded chunk")
    if not np.array_equal(ends[:-1], starts[1:]):
        raise ValueError("Per-neuron offsets must be contiguous and ordered")
    return rows, starts, counts, params.checked()


def prepare_chunk(rows, starts, counts, params, *, store_bounds=False, strict=True,
                  bodies=None):
    """Prepare one decoded chunk and return its flat GPU-ready arrays.

    rows     structured array in cache record format (CACHE_RECORD)
    starts   per-neuron first row in rows
    counts   per-neuron vertex count (segment count is count - 1 for a tree)
    params   Params instance
    bodies   per-neuron body ids taken from the authenticated manifest; without
             them the row 'id' of each first vertex is used, which is the SWC
             point id and only matches the body id in legacy single-cell use.
    """
    rows, starts, counts, params = _checked_layout(rows, starts, counts, params)
    ncell = starts.shape[0]
    ns = params.nseg

    plan = np.zeros((ncell, 9), dtype=np.int64)
    size_err = np.zeros(ncell, dtype=np.int32)
    _size_kernel(rows, starts, counts, np.int64(ns), plan, size_err)

    n_edges = plan[:, 2]
    seg_counts = plan[:, 3] * ns
    node_counts = seg_counts + plan[:, 4]
    # Junction endpoints, not junction slots: every edge contributes two
    # node endpoints and two per internal junction, so a cell with V vertices
    # needs 2 * E * ns endpoint slots while it only owns V + E * (ns - 1)
    # junction offsets. Sizing the shared base by slots let a dense
    # morphology overflow into the next cell's endpoint block.
    junc_counts = 2 * n_edges * ns
    val = size_err == 0
    if strict and not val.all():
        _raise_cell_error(size_err, np.flatnonzero(~val), starts, counts)

    seg_base = np.zeros(ncell + 1, dtype=np.int64)
    node_base = np.zeros(ncell + 1, dtype=np.int64)
    junc_base = np.zeros(ncell + 1, dtype=np.int64)
    np.cumsum(seg_counts, out=seg_base[1:])
    np.cumsum(node_counts, out=node_base[1:])
    np.cumsum(junc_counts, out=junc_base[1:])
    total_segments = int(seg_base[-1])
    total_nodes = int(node_base[-1])
    total_junctions = int(junc_base[-1])

    block = _allocate(total_segments, total_nodes, total_junctions, ncell, store_bounds)
    order = np.arange(ncell, dtype=np.int64)
    chunk_of_cell = np.zeros(ncell, dtype=np.int64)
    err = np.zeros(ncell, dtype=np.int32)
    _prepare_kernel(
        rows,
        order,
        chunk_of_cell,
        starts,
        counts,
        seg_base[:-1],
        node_base[:-1],
        junc_base[:-1],
        np.int64(ns),
        np.float64(params.axial_resistivity),
        np.asarray(params.source_um, dtype=np.float64),
        np.asarray(params.return_um, dtype=np.float64),
        np.float64(params.current_na),
        np.float64(params.conductivity_s_m),
        np.float64(params.clearance_um),
        np.int8(1 if store_bounds else 0),
        *block["kernel_arrays"],
        *block["cell_arrays"],
        err,
        block["cell_out"],
    )
    if strict and not bool((err == 0).all()):
        bad = np.flatnonzero(err != 0)
        _raise_cell_error(err, bad, starts, counts)
    return _assemble(rows, starts, counts, seg_base, node_base, junc_base, err, block, params,
                     store_bounds, bodies)


def _raise_cell_error(err, bad, starts, counts):
    first = int(bad[0])
    code = int(err[first])
    raise PrepareError(
        "Cell %d (%d vertices): %s" % (first, int(counts[first]), _MESSAGES.get(code, "invalid"))
    )


def _allocate(total_segments, total_nodes, total_junctions, ncell, store_bounds):
    """One allocation block per chunk; no per-cell Python objects."""
    kernel_arrays = (
        np.zeros(total_segments, dtype=np.float64),           # area
        np.zeros((total_segments, 3), dtype=np.float64) if store_bounds else np.zeros((0, 3)),
        np.zeros((total_segments, 3), dtype=np.float64) if store_bounds else np.zeros((0, 3)),
        np.zeros((total_segments, 3), dtype=np.float64),      # midpoints
        np.zeros(total_segments, dtype=np.float64),           # field_mv
        np.zeros(total_segments, dtype=np.float64),           # field_current_na
        np.zeros(total_nodes, dtype=np.int64),                # parents
        np.zeros(total_nodes, dtype=np.float64),              # conductances
        np.zeros(total_segments, dtype=np.int64),             # segment_nodes
        np.zeros(total_segments, dtype=np.int64),             # segment_ids
        np.zeros(total_segments, dtype=np.int32),             # segment_index
        np.zeros(total_segments, dtype=np.float64),           # parent_resistance
        np.zeros(max(total_junctions, 1), dtype=np.float64),  # child_resistance (per edge slot)
        np.zeros(max(total_segments, 1), dtype=np.int32),     # edge_rows
        np.zeros(total_junctions + 1, dtype=np.int64),        # junction_offsets
        np.zeros(2 * total_segments, dtype=np.int64),         # junction_segments
        np.zeros(2 * total_segments, dtype=np.float64),       # junction_conductances
        np.zeros(total_junctions, dtype=np.float64),          # junction_voltage_mv
    )
    cell_arrays = (
        np.zeros(ncell, dtype=np.int64),
        np.zeros(ncell, dtype=np.int64),
        np.zeros(ncell, dtype=np.int64),
        np.zeros(ncell, dtype=np.int64),
        np.zeros(ncell, dtype=np.int64),
        np.zeros(ncell, dtype=np.int64),
    )
    return {
        "kernel_arrays": kernel_arrays,
        "cell_arrays": cell_arrays,
        "cell_out": np.zeros(ncell, dtype=np.int64),
        "names": (
            "area starts ends midpoints field_mv field_current_na parents conductances "
            "segment_nodes segment_ids segment_index parent_resistance child_resistance "
            "edge_rows junction_offsets junction_segments junction_conductances "
            "junction_voltage_mv"
        ).split(),
        "cell_names": (
            "edge_counts segment_counts node_counts junction_counts component_counts "
            "max_junction_members"
        ).split(),
    }


def _assemble(rows, starts, counts, seg_base, node_base, junc_base, err, block, params,
              store_bounds, bodies=None):
    arrays = dict(zip(block["names"], block["kernel_arrays"]))
    cell_arrays = dict(zip(block["cell_names"], block["cell_arrays"]))
    ncell = starts.shape[0]
    # The skeleton body id is manifest metadata, not a vertex attribute: row
    # 'id' carries the SWC point id, which restarts at 1 inside every cell.
    if bodies is None:
        ids = np.empty(ncell, dtype=np.int64)
        for index in range(ncell):
            ids[index] = int(rows["id"][int(starts[index])])
    else:
        ids = np.asarray(bodies, dtype=np.int64)
        if ids.shape != (ncell,):
            raise ValueError("Per-neuron body ids must match the offset arrays")
    initial = np.empty((ncell, 3), dtype=np.float64)
    initial[:] = HH_INITIAL_GATES
    return PreparedChunk(
        body_ids=ids,
        segment_offsets=seg_base,
        node_offsets=node_base,
        junction_offsets=junc_base,
        area=arrays["area"],
        parents=arrays["parents"],
        conductances=arrays["conductances"],
        segment_nodes=arrays["segment_nodes"],
        field_mv=arrays["field_mv"],
        field_current_na=arrays["field_current_na"],
        segment_ids=arrays["segment_ids"],
        segment_index=arrays["segment_index"],
        edge_rows=arrays["edge_rows"],
        parent_resistance=arrays["parent_resistance"],
        child_resistance=arrays["child_resistance"][: seg_base[-1] and (seg_base[-1] // params.nseg)]
        if False
        else arrays["child_resistance"],
        starts_um=arrays["starts"],
        ends_um=arrays["ends"],
        midpoints_um=arrays["midpoints"],
        junction_segments=arrays["junction_segments"],
        junction_conductances=arrays["junction_conductances"],
        junction_voltage_mv=arrays["junction_voltage_mv"],
        error_codes=err,
        edge_counts=cell_arrays["edge_counts"],
        segment_counts=cell_arrays["segment_counts"],
        node_counts=cell_arrays["node_counts"],
        junction_counts=cell_arrays["junction_counts"],
        component_counts=cell_arrays["component_counts"],
        max_junction_members=cell_arrays["max_junction_members"],
        initial_gates=initial,
        params=params,
    )
