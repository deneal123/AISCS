"""NEURON-free authenticated preparation for the experimental GPU solver.

Reads authenticated packed-geometry cache chunks in parallel, prepares them
with the vectorised :mod:`fast_cable` kernel and returns the per-cell solver
dictionaries :func:`.batch_solver.solve_prepared_batch` expects. Every check
of the reference NEURON path is preserved: manifest digest, audited source
index, per-chunk SHA-256, compression bounds and the record layout.
"""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .fast_cable import (
    CACHE_RECORD,
    HH_INITIAL_GATES,
    HH_INITIAL_VOLTAGE_MV,
    prepare_chunk,
)

__all__ = [
    "FastPrepareError",
    "cells_from_chunk",
    "iter_prepared_chunks",
    "prepare_descriptor_chunk",
    "read_manifest",
]

_DIGEST = re.compile(r"[0-9a-f]{64}")
_IDENTITY = re.compile(r"[1-9][0-9]*")
CHUNK_FORMAT = "malecns-packed-geometry-chunk-v1"
CACHE_FORMAT = "malecns-packed-geometry-cache-v1"
MAX_VERTICES = 1_000_000


class FastPrepareError(ValueError):
    """Raised where the authenticated cache cannot be used."""


def read_manifest(directory, *, expected_manifest_sha256, graph_sha256=None,
                  source_index_sha256=None):
    """Return the verified manifest of a compatible packed geometry cache."""
    if (not isinstance(expected_manifest_sha256, str)
            or not _DIGEST.fullmatch(expected_manifest_sha256)):
        raise FastPrepareError("Invalid geometry cache manifest identity")
    directory = Path(directory)
    try:
        raw = (directory / "manifest.json").read_bytes()
    except OSError as exc:
        raise FastPrepareError("Geometry cache manifest unavailable") from exc
    if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
        raise FastPrepareError("Geometry cache manifest checksum mismatch")
    try:
        metadata = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FastPrepareError("Geometry cache manifest unreadable") from exc
    if (not isinstance(metadata, dict) or metadata.get("format") != CACHE_FORMAT
            or not isinstance(metadata.get("chunks"), list) or not metadata["chunks"]
            or type(metadata.get("vertices")) is not int or metadata["vertices"] < 1):
        raise FastPrepareError("Geometry cache manifest does not match snapshot")
    if graph_sha256 is not None and metadata.get("graph_sha256") != graph_sha256:
        raise FastPrepareError("Geometry cache belongs to another graph")
    if (source_index_sha256 is not None
            and metadata.get("source_index_sha256") != source_index_sha256):
        raise FastPrepareError("Geometry cache source index mismatch")
    # Match the canonical cache reader's producer check. A valid manifest hash
    # authenticates the snapshot but does not prove that its producing geometry
    # code is compatible with the current implementation.
    from service.infrastructure.stimulation.geometry_cache import cache
    from service.infrastructure.stimulation.geometry_cache.producer_compatibility import (
        producer_is_compatible,
    )

    if not producer_is_compatible(expected_manifest_sha256, metadata.get('producer_sha256'),
                                  cache._producer_sha256()):
        raise FastPrepareError("Geometry cache producer is not compatible")
    return {**metadata, "directory": directory}


def _checked_descriptor(descriptor, position, audited_sources):
    """Validate one descriptor; return (compression, [(body, source, offset, n)])."""
    if (not isinstance(descriptor, dict)
            or descriptor.get("name") != f"chunk-{position:06d}.bin"
            or descriptor.get("format") != CHUNK_FORMAT
            or type(descriptor.get("vertices")) is not int
            or not 1 <= descriptor["vertices"] <= MAX_VERTICES
            or type(descriptor.get("bytes")) is not int or descriptor["bytes"] <= 0
            or not isinstance(descriptor.get("sha256"), str)
            or not _DIGEST.fullmatch(descriptor["sha256"])
            or not isinstance(descriptor.get("neurons"), list)
            or not descriptor["neurons"]):
        raise FastPrepareError("Invalid packed geometry descriptor")
    raw_size = descriptor["vertices"] * CACHE_RECORD.itemsize
    compression = descriptor.get("compression", "none")
    if ((compression == "none" and descriptor["bytes"] != raw_size)
            or (compression == "zlib-1"
                and (descriptor.get("uncompressed_bytes") != raw_size
                     or descriptor["bytes"] > raw_size + 65536))
            or compression not in ("none", "zlib-1")):
        raise FastPrepareError("Invalid packed geometry compression")
    offset = 0
    seen = set()
    rows_of = []
    for item in descriptor["neurons"]:
        if (not isinstance(item, dict) or type(item.get("offset")) is not int
                or item["offset"] != offset or type(item.get("count")) is not int
                or item["count"] <= 0):
            raise FastPrepareError("Invalid packed geometry layout")
        body = item.get("body_id")
        source = item.get("source_sha256")
        if (not isinstance(body, str) or not _IDENTITY.fullmatch(body)
                or int(body) >= 2 ** 63 or not isinstance(source, str)
                or not _DIGEST.fullmatch(source)
                or audited_sources.get(int(body)) != source):
            raise FastPrepareError("Packed geometry source identity mismatch")
        if body in seen:
            raise FastPrepareError("Duplicate packed geometry source")
        seen.add(body)
        rows_of.append((int(body), source, offset, item["count"]))
        offset += item["count"]
    if offset != descriptor["vertices"]:
        raise FastPrepareError("Invalid packed geometry layout")
    return compression, rows_of


def _decode(path, compression, descriptor):
    """Read, authenticate and inflate one chunk file."""
    raw_size = descriptor["vertices"] * CACHE_RECORD.itemsize
    with Path(path).open("rb") as stream:
        raw = stream.read(descriptor["bytes"] + 1)
    if len(raw) != descriptor["bytes"]:
        raise FastPrepareError("Packed geometry chunk is truncated")
    if hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
        raise FastPrepareError("Packed geometry checksum mismatch")
    if compression == "zlib-1":
        try:
            decoder = zlib.decompressobj()
            decoded = decoder.decompress(raw, raw_size + 1)
        except zlib.error as exc:
            raise FastPrepareError("Invalid compressed geometry") from exc
        if (len(decoded) != raw_size or not decoder.eof or decoder.unused_data
                or decoder.unconsumed_tail):
            raise FastPrepareError("Invalid compressed geometry")
        raw = decoded
    return np.frombuffer(raw, dtype=CACHE_RECORD)


def iter_prepared_chunks(metadata, *, audited_sources, params, workers=4,
                         limit=None, progress=None, on_invalid=None, order=None,
                         store_bounds=False, replacement_factory=None, on_replacement=None):
    """Yield (bodies, cells, chunk) for each authenticated cache chunk.

    Decoding (read, SHA-256, inflate) runs in a bounded thread pool because all
    three release the interpreter lock; preparation itself runs in the numba
    kernel. Both stages stay ordered with respect to the visiting order.

    The optional order lists chunk positions to visit instead of 0..n-1, so a
    caller can plan the decode order (for example by morphology width) without
    weakening any identity check: the position index still selects the manifest
    descriptor it was validated against.
    ``limit`` is a number of cache chunks, not a number of neurons. A chunk
    may contain many cells, so it must not be used as a cell-count bound.
    Replacement callbacks are experimental; their receipts are provisional
    until the entire consumer calculation and its provenance checks succeed.
    """
    if type(store_bounds) is not bool:
        raise FastPrepareError('Invalid recording bounds option')
    if type(workers) is not int or not 1 <= workers <= 32:
        raise FastPrepareError("Invalid decode worker count")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise FastPrepareError("Invalid cache chunk limit")
    if on_invalid is not None and not callable(on_invalid):
        raise FastPrepareError("Invalid rejected-cell callback")
    if ((replacement_factory is None) != (on_replacement is None)
            or (replacement_factory is not None and
                (not callable(replacement_factory) or not callable(on_replacement)
                 or on_invalid is not None))):
        raise FastPrepareError('Replacement requires its own provenance callback')
    directory = metadata["directory"]
    chunks = metadata["chunks"]
    # Per-chunk hashes alone do not detect missing, repeated or substituted
    # chunks. Authenticate the entire identity inventory before yielding even
    # a partial result, including when the caller requests a chunk limit.
    if (not isinstance(audited_sources, dict) or not audited_sources
            or type(metadata.get('neurons')) is not int
            or metadata['neurons'] != len(audited_sources)
            or type(metadata.get('vertices')) is not int):
        raise FastPrepareError("Invalid geometry snapshot inventory")
    verified = []
    seen_bodies = set()
    total_vertices = 0
    for position, descriptor in enumerate(chunks):
        compression, rows_of = _checked_descriptor(descriptor, position, audited_sources)
        for body, _source, _offset, _count in rows_of:
            if body in seen_bodies:
                raise FastPrepareError("Duplicate morphology across chunks")
            seen_bodies.add(body)
        total_vertices += descriptor['vertices']
        verified.append((compression, rows_of))
    if seen_bodies != set(audited_sources) or total_vertices != metadata['vertices']:
        raise FastPrepareError("Incomplete geometry snapshot inventory")
    positions = list(range(len(chunks))) if order is None else order
    if order is not None and (not isinstance(order, (list, tuple))
                              or len(order) != len(chunks)
                              or any(type(value) is not int or not 0 <= value < len(chunks)
                                     for value in order)
                              or len(set(order)) != len(chunks)):
        raise FastPrepareError("Invalid chunk visiting order")
    plan = []
    for position in positions:
        if limit is not None and len(plan) >= limit:
            break
        descriptor = chunks[position]
        compression, rows_of = verified[position]
        plan.append((directory / descriptor["name"], compression, rows_of, descriptor))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        window = []
        pending = list(plan)
        while pending or window:
            while pending and len(window) < workers:
                item = pending.pop(0)
                window.append((item, pool.submit(_decode, item[0], item[1], item[3])))
            if not window:
                break
            (path, compression, rows_of, descriptor), future = window.pop(0)
            rows = future.result()
            bodies = [row[0] for row in rows_of]
            sources = {row[0]: row[1] for row in rows_of}
            starts = np.zeros(len(rows_of), dtype=np.int64)
            counts = np.zeros(len(rows_of), dtype=np.int64)
            for index, (_body, _source, first, count) in enumerate(rows_of):
                starts[index] = first
                counts[index] = count
            chunk = prepare_chunk(rows, starts, counts, params, strict=False, bodies=bodies,
                                  store_bounds=store_bounds)
            rejected = []
            invalid_handler = ((lambda body, code, result=rejected: result.append((body, code)))
                               if replacement_factory is not None else on_invalid)
            kept = _usable(chunk, bodies, on_invalid=invalid_handler)
            cells = cells_from_chunk(chunk, sources=sources, selected=kept)
            if rejected:
                for body, code in rejected:
                    replacement, receipt = replacement_factory(body, code, sources[body])
                    if (not isinstance(replacement, dict) or replacement.get('id') != body
                            or not isinstance(receipt, dict)
                            or receipt.get('source_sha256') != sources[body]
                            or not isinstance(receipt.get('derived_sha256'), str)
                            or len(receipt['derived_sha256']) != 64
                            or any(c not in '0123456789abcdef' for c in receipt['derived_sha256'])
                            or replacement.get('morphology_sha256') != receipt['derived_sha256']):
                        raise FastPrepareError('Invalid replacement identity')
                    on_replacement(body, code, receipt)
                    cells.append(replacement)
                by_id = {cell['id']: cell for cell in cells}
                cells = [by_id[body] for body in bodies]
            if progress is not None:
                progress(descriptor["name"], len(cells), len(rows))
            yield [cell['id'] for cell in cells], cells, chunk


def prepare_descriptor_chunk(directory, descriptor, *, position, audited_sources, params):
    """Prepare one chunk straight from its manifest descriptor."""
    compression, rows_of = _checked_descriptor(descriptor, position, audited_sources)
    rows = _decode(Path(directory) / descriptor["name"], compression, descriptor)
    starts = np.zeros(len(rows_of), dtype=np.int64)
    counts = np.zeros(len(rows_of), dtype=np.int64)
    for index, (_body, _source, first, count) in enumerate(rows_of):
        starts[index] = first
        counts[index] = count
    bodies = [row[0] for row in rows_of]
    chunk = prepare_chunk(rows, starts, counts, params, bodies=bodies)
    return cells_from_chunk(chunk, sources={row[0]: row[1] for row in rows_of}), chunk


def _usable(chunk, bodies, *, on_invalid=None):
    """Indices of prepared cells, reporting the ones the kernel rejected.

    Rejected cells must never disappear silently from a population. Callers
    explicitly accepting partial results must supply a callback and retain its
    cell IDs and error codes. Otherwise stop the calculation.
    """
    codes = np.asarray(chunk.error_codes)
    if codes.shape != (len(bodies),) or codes.dtype.kind not in 'iu':
        raise FastPrepareError("Invalid morphology error codes")
    if not codes.any():
        return list(range(len(bodies)))
    kept = []
    for index, code in enumerate(codes):
        if int(code) == 0:
            kept.append(index)
        elif on_invalid is None:
            raise FastPrepareError(f"Rejected morphology {int(bodies[index])}: code {int(code)}")
        else:
            on_invalid(int(bodies[index]), int(code))
    return kept


def cells_from_chunk(chunk, *, sources=None, selected=None):
    """Split flat prepared arrays into per-cell solver inputs (array views)."""
    segment = chunk.segment_offsets
    node = chunk.node_offsets
    cells = []
    for index in (range(len(chunk.body_ids)) if selected is None else selected):
        s0, s1 = int(segment[index]), int(segment[index + 1])
        n0, n1 = int(node[index]), int(node[index + 1])
        body = int(chunk.body_ids[index])
        cells.append({
            "id": body,
            "geometry": {
                "area": chunk.area[s0:s1],
                "parents": chunk.parents[n0:n1],
                "conductances": chunk.conductances[n0:n1],
                "segment_nodes": chunk.segment_nodes[s0:s1],
                "starts_um": chunk.starts_um[s0:s1],
                "ends_um": chunk.ends_um[s0:s1],
                "midpoints_um": chunk.midpoints_um[s0:s1],
                "endpoint_radii_um": chunk.endpoint_radii_um[s0:s1],
                "edge_node_ids": chunk.segment_ids[s0:s1],
                "segment_index": chunk.segment_index[s0:s1],
                "grid": None,
            },
            "field_current_na": chunk.field_current_na[s0:s1],
            "field_mv": chunk.field_mv[s0:s1],
            "events": [],
            "initial_voltage_mv": HH_INITIAL_VOLTAGE_MV,
            "initial_gates": HH_INITIAL_GATES,
            "morphology_sha256": None if sources is None else sources.get(body),
            "vertices": int(chunk.node_counts[index] - chunk.segment_counts[index]),
            "components": int(chunk.component_counts[index]),
        })
    return cells
