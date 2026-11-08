"""Conservative contact screening against an independently audited SWC snapshot."""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import re
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing
from pathlib import Path

import numpy as np

from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.stimulation.contact_clearances import (
    contact_clearances,
    packed_contact_clearances,
)
from service.infrastructure.stimulation.segment_lookup import segment_ordinals


def _sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _contact_clearances(swc, points, *, probe_indices=None, probe_clearance_um=None):
    return contact_clearances(swc, points, probe_indices=probe_indices,
                              probe_clearance_um=probe_clearance_um)


def _check_screen_candidate(arguments):
    body, digest, directories, points, clearance_um, candidate_indices = arguments
    try:
        swc = read_skeleton(body, directories, expected_sha256=digest)['swc']
    except (ValueError, FileNotFoundError) as exc:
        raise ValueError('Candidate source changed since indexing') from exc
    # Points outside the audited, radius-expanded bounding box cannot be
    # within clearance of this SWC. Check only possible intersections first;
    # for a flagged cell retain the original complete distance report.
    distances = _contact_clearances(swc, points, probe_indices=candidate_indices,
                                    probe_clearance_um=clearance_um)
    if distances is not None:
        return {'body_id': body, 'source_sha256': digest,
                'contact_indices': [i for i, value in enumerate(distances)
                                    if value <= clearance_um],
                'conservative_clearance_um': distances}
    return None


def screen_contacts(bounds: Path, bounds_audit: Path, radii: Path, radii_audit: Path,
                    graph_ids, graph_sha: str, directories: list[Path], contacts, clearance_um,
                    *, segment_index: Path | None = None, segment_audit: Path | None = None,
                    workers: int = 1, geometry_cache: dict | None = None):
    """Report potential intersections without inferring excitation or tissue anatomy.

    All four contacts and every indexed morphology are screened. The filter
    expands each verified centerline box by that cell's maximum radius plus
    clearance. Returned candidates are checked against the source geometry;
    maximum endpoint radii make their cable clearances conservative.
    Completeness applies only to the immutable audited source snapshot.
    """
    return _screen_positions(bounds, bounds_audit, radii, radii_audit, graph_ids,
                             graph_sha, directories, contacts, clearance_um,
                             segment_index=segment_index, segment_audit=segment_audit,
                             workers=workers, expected_four=True, geometry_cache=geometry_cache)


def screen_contact_positions(bounds: Path, bounds_audit: Path, radii: Path, radii_audit: Path,
                             graph_ids, graph_sha: str, directories: list[Path], contacts,
                             clearance_um, *, segment_index: Path | None = None,
                             segment_audit: Path | None = None, workers: int = 1,
                             geometry_cache: dict | None = None):
    """Screen up to 64 proposed positions against one audited snapshot.

    This checks each point independently. It does not validate electrode pairs,
    placement on the body, tissue geometry, or whether a position is reachable.
    """
    return _screen_positions(bounds, bounds_audit, radii, radii_audit, graph_ids,
                             graph_sha, directories, contacts, clearance_um,
                             segment_index=segment_index, segment_audit=segment_audit,
                             workers=workers, expected_four=False, geometry_cache=geometry_cache)


def _screen_positions(bounds, bounds_audit, radii, radii_audit, graph_ids, graph_sha,
                      directories, contacts, clearance_um, *, segment_index, segment_audit,
                      workers, expected_four, geometry_cache):
    points = np.asarray(contacts, dtype=float)
    if (points.ndim != 2 or points.shape[1:] != (3,)
            or (len(points) != 4 if expected_four else not 1 <= len(points) <= 64)
            or not np.isfinite(points).all()
            or isinstance(clearance_um, bool | np.bool_)
            or not isinstance(clearance_um, int | float)
            or not math.isfinite(clearance_um) or clearance_um <= 0):
        raise ValueError("Invalid contacts or clearance")
    if (segment_index is None) != (segment_audit is None):
        raise ValueError("Both segment index and audit are required")
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("Screening workers must be between 1 and 8")
    ids = [int(value) for value in graph_ids]
    if (not ids or any(value <= 0 for value in ids)
            or any(a >= b for a, b in zip(ids, ids[1:], strict=False))):
        raise ValueError("Invalid graph IDs")
    try:
        bproof = json.loads(bounds_audit.read_text(encoding="utf8"))
        rproof = json.loads(radii_audit.read_text(encoding="utf8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Independent audit report unavailable") from exc
    if (not isinstance(bproof, dict) or not isinstance(rproof, dict)
            or bproof.get("format") != "malecns-bounds-audit-v1"
            or rproof.get("format") != "malecns-radius-audit-v1"
            or type(bproof.get("verified")) is not int or bproof["verified"] != len(ids)
            or type(rproof.get("verified")) is not int or rproof["verified"] != len(ids)
            or bproof.get("graph_sha256") != graph_sha or rproof.get("graph_sha256") != graph_sha
            or rproof.get("source_sha256") != bproof.get("index_sha256")
            or not all(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
                       for value in (bproof.get("index_sha256"), rproof.get("index_sha256")))):
        raise ValueError("Audit reports do not match graph")
    if _sha(bounds) != bproof["index_sha256"] or _sha(radii) != rproof["index_sha256"]:
        raise ValueError("Index changed since independent audit")
    with closing(sqlite3.connect(bounds.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        bm = dict(db.execute("SELECT key, value FROM metadata"))
        brows = db.execute("SELECT body_id,status,sha256,min_x,max_x,min_y,max_y,min_z,max_z "
                           "FROM bounds ORDER BY body_id").fetchall()
    with closing(sqlite3.connect(radii.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        rm = dict(db.execute("SELECT key, value FROM metadata"))
        rrows = db.execute("SELECT ordinal,body_id,sha256,radius_um FROM radii ORDER BY ordinal")
        rrows = rrows.fetchall()
    if (bm.get("format") != "malecns-verified-bounds-v1" or bm.get("graph_sha256") != graph_sha
            or bm.get("neurons") != str(len(ids)) or rm.get("format") != "malecns-radius-bounds-v1"
            or rm.get("graph_sha256") != graph_sha or rm.get("neurons") != str(len(ids))
            or rm.get("source_sha256") != bproof["index_sha256"]
            or not re.fullmatch(r"[a-f0-9]{64}", rm.get("algorithm_sha256", ""))
            or len(brows) != len(ids) or len(rrows) != len(ids)):
        raise ValueError("Indexes do not match graph")
    eligible, segment_hash = None, None
    if segment_index is not None:
        if any(type(row[3]) not in (int, float) or not math.isfinite(row[3]) or row[3] < 0
               for row in rrows):
            raise ValueError("Invalid or incomplete radius index")
        margin = max(row[3] for row in rrows) + clearance_um
        if not math.isfinite(margin):
            raise ValueError("Contact screening overflow")
        with np.errstate(over="ignore", invalid="ignore"):
            if not np.isfinite(np.abs(points) + margin).all():
                raise ValueError("Contact screening overflow")
        eligible, segment_hash = segment_ordinals(
            segment_index, segment_audit, source_sha=bproof["index_sha256"], graph_sha=graph_sha,
            count=len(ids), contacts=points, radius_um=margin, return_digest=True)
    matches = []
    points_list = points.tolist()
    for ordinal, (body, bound, radius) in enumerate(zip(ids, brows, rrows, strict=True)):
        if (bound[0] != body or bound[1] != "ok" or not isinstance(bound[2], str)
                or not re.fullmatch(r"[a-f0-9]{64}", bound[2])
                or (radius[0], radius[1], radius[2]) != (ordinal, body, bound[2])
                or type(radius[3]) not in (int, float) or not math.isfinite(radius[3])
                or radius[3] < 0
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in bound[3:])
                or any(bound[3 + 2 * axis] > bound[4 + 2 * axis] for axis in range(3))):
            raise ValueError("Invalid or incomplete index entry")
        if eligible is not None and ordinal not in eligible:
            continue
        margin = radius[3] + clearance_um
        if not math.isfinite(margin):
            raise ValueError("Contact screening overflow")
        with np.errstate(over="ignore", invalid="ignore"):
            lower = np.asarray(bound[3::2]) - margin
            upper = np.asarray(bound[4::2]) + margin
        if not np.isfinite(lower).all() or not np.isfinite(upper).all():
            raise ValueError("Contact screening overflow")
        candidate_indices = np.flatnonzero(
            np.all((points >= lower) & (points <= upper), axis=1)).tolist()
        if not candidate_indices:
            continue
        matches.append((body, bound[2], directories, points_list, clearance_um, candidate_indices))
    flagged = []
    if geometry_cache is not None:
        from service.infrastructure.stimulation.geometry_cache.selected import iter_selected_cache
        from service.infrastructure.stimulation.geometry_prefetch import prefetch

        if (not isinstance(geometry_cache, dict)
                or set(geometry_cache) != {'directory', 'expected_manifest_sha256',
                                           'source_index', 'source_audit'}
                or any(not isinstance(geometry_cache[key], Path)
                       for key in ('directory', 'source_index', 'source_audit'))
                or geometry_cache['source_index'].resolve() != bounds.resolve()
                or geometry_cache['source_audit'].resolve() != bounds_audit.resolve()):
            raise ValueError('Invalid screening geometry cache configuration')
        expected = {item[0]: item for item in matches}
        entries = prefetch(iter_selected_cache(**geometry_cache, graph_ids=ids,
                                              graph_sha256=graph_sha,
                                              selected_ids=list(expected)))
        try:
            for entry in entries:
                body = int(entry['skeleton']['body_id'])
                _, digest, _, positions, distance, probes = expected[body]
                if entry['skeleton']['sha256'] != digest:
                    raise ValueError('Candidate source differs from indexed snapshot')
                values = packed_contact_clearances(entry['geometry'], positions,
                    probe_indices=probes, probe_clearance_um=distance)
                if values is not None:
                    flagged.append({'body_id': body, 'source_sha256': digest,
                                    'contact_indices': [i for i, value in enumerate(values)
                                                        if value <= distance],
                                    'conservative_clearance_um': values})
        finally:
            entries.close()
    elif workers > 1 and len(matches) > 1:
        with ProcessPoolExecutor(max_workers=workers,
                                 mp_context=multiprocessing.get_context('spawn')) as executor:
            for start in range(0, len(matches), 128):
                flagged.extend(row for row in executor.map(
                    _check_screen_candidate, matches[start:start + 128], chunksize=4)
                    if row is not None)
    else:
        flagged.extend(row for row in map(_check_screen_candidate, matches) if row is not None)
    if _sha(bounds) != bproof["index_sha256"] or _sha(radii) != rproof["index_sha256"]:
        raise ValueError("Index changed during query")
    return {"potential_intersections": flagged, "examined": len(matches), "indexed": len(ids),
            "index_sha256": {"bounds": bproof["index_sha256"], "radii": rproof["index_sha256"],
                             "segments": segment_hash},
            "coordinate_frame": "male-cns-v1.0-native-um",
            "interpretation": "conservative SWC snapshot screening; "
                              "not tissue anatomy or activation"}
