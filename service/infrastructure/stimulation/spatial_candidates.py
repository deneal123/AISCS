"""Exact centerline proximity against a complete verified morphology snapshot.

This is geometric screening, not an excitation prediction or tissue model.
The result refers to the indexed source snapshot; source changes after indexing
can invalidate completeness even when returned candidates still verify.
"""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import re
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.stimulation.segment_lookup import segment_ordinals


def closest_swc_segment(swc: str, contacts, *, recording_contacts=None, extra_contacts=None,
                        probe_indices=None, probe_clearance_um=None):
    """Find the closest STIM edge and optionally check recording clearances.

    A single parse of the SWC serves both pairs; recording contacts never
    participate in the choice of the closest stimulation edge.
    """
    electrode = np.asarray(contacts, dtype=float)
    if electrode.shape != (2, 3) or not np.isfinite(electrode).all():
        raise ValueError("Expected two finite contact positions")
    if recording_contacts is not None:
        recording = np.asarray(recording_contacts, dtype=float)
        if recording.shape != (2, 3) or not np.isfinite(recording).all():
            raise ValueError("Invalid recording contacts")
        electrode = np.concatenate((electrode, recording))
    if extra_contacts is not None:
        extra = np.asarray(extra_contacts, dtype=float)
        if (recording_contacts is None or extra.ndim != 2 or extra.shape[1:] != (3,)
                or not 1 <= len(extra) <= 60 or not np.isfinite(extra).all()):
            raise ValueError("Invalid additional contacts")
        electrode = np.concatenate((electrode, extra))
    if probe_indices is not None:
        if (not probe_indices or len(set(probe_indices)) != len(probe_indices)
                or any(type(i) is not int or i < 0 or i >= len(electrode) for i in probe_indices)
                or not isinstance(probe_clearance_um, int | float)
                or isinstance(probe_clearance_um, bool) or not math.isfinite(probe_clearance_um)):
            raise ValueError("Invalid screening probe")
    nodes, radii = {}, {}
    for line in swc.splitlines():
        row = line.strip()
        if not row or row.startswith("#"):
            continue
        fields = row.split()
        if len(fields) != 7:
            raise ValueError("Malformed SWC")
        node, parent = int(fields[0]), int(fields[6])
        point = np.asarray([float(value) * .008 for value in fields[2:5]])
        radius = float(fields[5]) * .008
        if (node <= 0 or node >= 2**63 or node in nodes or not np.isfinite(point).all()
                or not math.isfinite(radius) or radius < 0):
            raise ValueError("Invalid SWC vertex")
        nodes[node] = (point, parent)
        radii[node] = radius
    if not nodes:
        raise ValueError("Empty SWC")
    parents_with_children = {parent for _, parent in nodes.values() if parent != -1}
    starts, ends, node_ids, isolated, radii_max = [], [], [], [], []
    components = isolated_roots = nonpositive_radius_edges = 0
    for node, (end, parent) in nodes.items():
        if parent == -1:
            components += 1
            # An isolated root is geometry but cannot be used as a cable edge.
            if node not in parents_with_children:
                isolated_roots += 1
                starts.append(end)
                ends.append(end)
                node_ids.append(node)
                isolated.append(True)
                radii_max.append(radii[node])
            continue
        if parent not in nodes:
            raise ValueError("Missing SWC parent")
        nonpositive_radius_edges += int(radii[node] <= 0 or radii[parent] <= 0)
        starts.append(nodes[parent][0])
        ends.append(end)
        node_ids.append(node)
        isolated.append(False)
        radii_max.append(max(radii[node], radii[parent]))
    if not node_ids:
        raise ValueError("No SWC geometry")
    starts, ends = np.asarray(starts), np.asarray(ends)
    delta = ends - starts
    length2 = np.einsum("ij,ij->i", delta, delta)
    if not np.isfinite(length2).all():
        raise ValueError("Segment geometry exceeds numerical range")
    candidates, clearances = [], [None] * len(electrode)
    order = (list(probe_indices) + [i for i in range(len(electrode)) if i not in probe_indices]
             if probe_indices is not None else list(range(len(electrode))))
    radii_max = np.asarray(radii_max)
    for ordinal, index in enumerate(order):
        position = electrode[index]
        numerator = np.einsum("ij,ij->i", position - starts, delta)
        fraction = np.zeros(len(node_ids), dtype=float)
        np.divide(numerator, length2, out=fraction, where=length2 > 0)
        np.clip(fraction, 0, 1, out=fraction)
        distances = np.linalg.norm(starts + fraction[:, None] * delta - position, axis=1)
        if not np.isfinite(fraction).all() or not np.isfinite(distances).all():
            raise ValueError("Contact geometry exceeds numerical range")
        clearances[index] = float(np.min(distances - radii_max))
        minimum = distances.min()
        tied = np.flatnonzero(distances == minimum)
        chosen = min(tied, key=lambda item: node_ids[item])
        if index < 2:
            candidates.append((float(distances[chosen]), node_ids[chosen], index,
                               float(fraction[chosen]), isolated[chosen]))
        if (probe_indices is not None and ordinal + 1 == len(probe_indices)
                and all(clearances[i] > probe_clearance_um for i in probe_indices)):
            return None
    zero_length_edges = int(np.count_nonzero((length2 == 0) & ~np.asarray(isolated)))
    distance, child, contact, fraction, isolated = min(candidates)
    result = {"distance_um": distance, "child_node_id": None if isolated else child,
            "contact": contact, "edge_fraction": fraction, "isolated_root": isolated,
            "conservative_clearance_um": clearances[:2],
            "geometry": {"components": components, "isolated_roots": isolated_roots,
                         "zero_length_edges": zero_length_edges,
                         "nonpositive_radius_edges": nonpositive_radius_edges}}
    if recording_contacts is not None:
        result["recording_clearance_um"] = clearances[2:4]
    if extra_contacts is not None:
        result["extra_clearance_um"] = clearances[4:]
    return result


def _check_candidate(item):
    body_id, sha, directories, contacts, radius_um, recording_contacts = item
    try:
        skeleton = read_skeleton(body_id, directories, expected_sha256=sha)
    except (ValueError, FileNotFoundError) as exc:
        raise ValueError("Candidate source changed since indexing") from exc
    closest = closest_swc_segment(skeleton["swc"], contacts,
                                  recording_contacts=recording_contacts)
    if closest["distance_um"] <= radius_um:
        return {"body_id": body_id, "source_sha256": sha, **closest}
    return None


def spatial_candidates(database: Path, graph_ids, graph_sha: str, directories: list[Path],
                       contacts, radius_um: float, *, audit_report: Path, workers: int = 1,
                       segment_index: Path | None = None, segment_audit: Path | None = None,
                       recording_contacts=None):
    """Return all indexed SWC centerlines within radius of either contact.

    An incomplete index is rejected. Every returned source is reread and
    compared to the indexed hash; this does not reverify noncandidates, so the
    completeness guarantee applies to the snapshot, not a changing directory.
    """
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("Spatial workers must be between 1 and 8")
    if (segment_index is None) != (segment_audit is None):
        raise ValueError("Both segment index and audit are required")
    electrode = np.asarray(contacts, dtype=float)
    recording = None if recording_contacts is None else np.asarray(recording_contacts, dtype=float)
    if recording is not None and (recording.shape != (2, 3) or not np.isfinite(recording).all()):
        raise ValueError("Invalid recording contacts")
    if (electrode.shape != (2, 3) or not np.isfinite(electrode).all()
            or isinstance(radius_um, bool) or not isinstance(radius_um, int | float)
            or not math.isfinite(radius_um) or radius_um < 0):
        raise ValueError("Invalid spatial query")
    with np.errstate(over="ignore"):
        if not np.isfinite(np.abs(electrode) + radius_um).all():
            raise ValueError("Spatial query exceeds numerical range")
    ids = [int(value) for value in graph_ids]
    if not ids or any(value <= 0 for value in ids) or any(
        a >= b for a, b in zip(ids, ids[1:], strict=False)
    ):
        raise ValueError("Invalid graph IDs")
    try:
        report = json.loads(audit_report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Independent audit report unavailable") from exc
    if (not isinstance(report, dict) or report.get("format") != "malecns-bounds-audit-v1"
            or type(report.get("verified")) is not int or report["verified"] != len(ids)
            or report.get("graph_sha256") != graph_sha
            or not isinstance(report.get("index_sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", report["index_sha256"])):
        raise ValueError("Independent audit report does not match graph")

    def index_digest():
        digest = hashlib.sha256()
        with database.open("rb") as source_file:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    if index_digest() != report["index_sha256"]:
        raise ValueError("Index changed since independent audit")
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        metadata = dict(db.execute("SELECT key, value FROM metadata"))
        if (metadata.get("format") != "malecns-verified-bounds-v1"
                or metadata.get("graph_sha256") != graph_sha
                or metadata.get("neurons") != str(len(ids))
                or not re.fullmatch(r"[a-f0-9]{64}", metadata.get("algorithm_sha256", ""))):
            raise ValueError("Index does not match graph")
        rows = db.execute("SELECT body_id, status, sha256, min_x, max_x, min_y, max_y, "
                          "min_z, max_z FROM bounds ORDER BY body_id").fetchall()
        if len(rows) != len(ids) or any(
            row[0] != expected or row[1] != "ok" or not isinstance(row[2], str)
            or not re.fullmatch(r"[a-f0-9]{64}", row[2])
            or any(not isinstance(value, int | float) or not math.isfinite(value)
                   for value in row[3:])
            or any(row[3 + axis * 2] > row[4 + axis * 2] for axis in range(3))
            for row, expected in zip(rows, ids, strict=True)
        ):
            raise ValueError("Index is incomplete or contains unavailable sources")
        clauses, args = [], []
        for x, y, z in electrode:
            clauses.append("(min_x<=? AND max_x>=? AND min_y<=? AND max_y>=? "
                           "AND min_z<=? AND max_z>=?)")
            args.extend([x + radius_um, x - radius_um, y + radius_um, y - radius_um,
                         z + radius_um, z - radius_um])
        matches = db.execute("SELECT body_id, sha256, min_x, max_x, min_y, max_y, min_z, max_z "
                             "FROM bounds WHERE " + " OR ".join(clauses), args).fetchall()
    if segment_index is not None:
        ordinals = segment_ordinals(segment_index, segment_audit, source_sha=report["index_sha256"],
                                    graph_sha=graph_sha, count=len(ids), contacts=electrode,
                                    radius_um=radius_um)
        eligible = {ids[ordinal] for ordinal in ordinals}
        matches = [row for row in matches if row[0] in eligible]
    result = []
    def tasks(batch):
        return [(row[0], row[1], directories, electrode.tolist(), radius_um,
                 None if recording is None else recording.tolist()) for row in batch]

    # Bounded batches avoid queuing every reconstruction at once. Each process
    # validates source bytes independently; completion order cannot affect output.
    if workers > 1 and len(matches) > 1:
        with ProcessPoolExecutor(max_workers=workers,
                                 mp_context=multiprocessing.get_context("spawn")) as executor:
            for offset in range(0, len(matches), 128):
                result.extend(item for item in executor.map(_check_candidate,
                              tasks(matches[offset:offset + 128]), chunksize=4) if item is not None)
    else:
        result.extend(item for item in map(_check_candidate, tasks(matches)) if item is not None)
    result.sort(key=lambda item: (item["distance_um"], item["body_id"]))
    if index_digest() != report["index_sha256"]:
        raise ValueError("Index changed during query")
    return {"candidates": result, "bounding_box_matches": len(matches), "indexed": len(ids),
            "coordinate_frame": "male-cns-v1.0-native-um",
            "interpretation": "centerline proximity in indexed snapshot; not excitation"}
