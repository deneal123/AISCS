"""Integrity audit for registered field-summary streams."""

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path


def failure_category(status, reason):
    """Classify failures without publishing arbitrary exception text or paths."""
    if status == "source_missing":
        return "source_missing"
    if status != "invalid_geometry_or_field":
        return None
    if reason in {
        "Observation point intersects a contact exclusion sphere",
        "Contact exclusion sphere intersects a cable segment",
        "Contact exclusion sphere intersects a degenerate cable segment",
        "Contact exclusion sphere intersects an isolated SWC vertex",
    }:
        return "contact_exclusion"
    return "other_geometry_or_field"


def audit(path: Path, ids, *, graph_hash: str, allow_partial: bool = False):
    count = 0
    statuses = Counter()
    failures = Counter()
    footer = None
    with path.open(encoding="utf-8") as stream:
        first = stream.readline()
        if not first.endswith("\n"):
            raise ValueError("Missing or incomplete header")
        header = json.loads(first)
        if (header.get("kind") != "header" or header.get("format") != "malecns-field-summary-v1"
                or header.get("graph_sha256") != graph_hash or header.get("neurons") != len(ids)
                or header.get("coordinate_frame") != "male-cns-v1.0-native-um"
                or header.get("medium") != "infinite-homogeneous-isotropic"
                or not isinstance(header.get("configuration"), dict)):
            raise ValueError("Invalid field provenance")
        algorithm = header.get("algorithm_sha256")
        backend, device = header.get("field_backend", "cpu"), header.get("device_info")
        if (not isinstance(backend, str) or backend not in {"cpu", "gpu"}
                or (backend == "cpu" and device is not None)):
            raise ValueError("Invalid field backend provenance")
        if backend == "gpu" and (
            not isinstance(device, dict) or set(device) != {
                "numba_version", "cuda_runtime", "device", "compute_capability"
            } or not all(isinstance(device.get(key), str) and device[key]
                         for key in ("numba_version", "device"))
            or any(not isinstance(device.get(key), list) or len(device[key]) != 2
                   or any(type(v) is not int or v < 0 for v in device[key])
                   for key in ("cuda_runtime", "compute_capability"))
        ):
            raise ValueError("Invalid GPU provenance")
        if "allow_degenerate" in header and type(header["allow_degenerate"]) is not bool:
            raise ValueError("Invalid partial geometry policy")
        if algorithm is not None and (not isinstance(algorithm, str)
                                      or not re.fullmatch(r"[0-9a-f]{64}", algorithm)):
            raise ValueError("Invalid algorithm identity")
        configuration = header["configuration"]
        for key in ("source_um", "return_um"):
            values = configuration.get(key)
            if (not isinstance(values, list) or len(values) != 3
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
                raise ValueError("Invalid field configuration")
        for key in ("current_na", "conductivity_s_m", "clearance_um"):
            value = configuration.get(key)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Invalid field configuration")
        if configuration["conductivity_s_m"] <= 0 or configuration["clearance_um"] <= 0:
            raise ValueError("Invalid field configuration")
        chain = hashlib.sha256(json.dumps(header, sort_keys=True).encode()).hexdigest()
        for line in stream:
            if not line.endswith("\n"):
                raise ValueError("Incomplete field record")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("Invalid field record")
            if row.get("kind") == "footer":
                footer = row
                if stream.read(1):
                    raise ValueError("Data follow the completion footer")
                break
            if count >= len(ids) or row.get("body_id") != str(ids[count]):
                raise ValueError("Field records do not match graph IDs")
            provided = row.pop("chain_sha256", None)
            canonical = json.dumps(
                row, allow_nan=False, sort_keys=True, separators=(",", ":")
            ).encode()
            chain = hashlib.sha256(bytes.fromhex(chain) + canonical).hexdigest()
            if chain != provided:
                raise ValueError("Field record checksum mismatch")
            status = row.get("status")
            if status in {"ok", "partial_geometry"}:
                curvature = row.get("max_abs_curvature_signed_mv_per_um2")
                source_sha = row.get("source_sha256")
                if (not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha)
                        or type(row.get("vertices")) is not int or row["vertices"] < 1
                        or type(row.get("curvature_vertices")) is not int
                        or not 0 <= row["curvature_vertices"] <= row["vertices"]
                        or (curvature is not None and (type(curvature) not in (int, float)
                                                        or not math.isfinite(curvature)))
                        or (curvature is None) != (row.get("extremum_vertex_id") is None)
                        or (curvature is None) != (row["curvature_vertices"] == 0)
                        or (curvature is not None and (
                            type(row.get("extremum_vertex_id")) is not int
                            or row["extremum_vertex_id"] <= 0))
                        or row.get("interpretation") != "field-only"):
                    raise ValueError("Invalid computed field record")
                omitted = row.get("omitted_zero_length_edges", 0)
                omitted_curvature = row.get("omitted_curvature_vertices", 0)
                if (type(omitted) is not int or type(omitted_curvature) is not int
                        or omitted < 0 or omitted_curvature < 0
                        or (status == "ok" and (omitted or omitted_curvature))
                        or (status == "partial_geometry" and
                            (omitted == 0 or header.get("allow_degenerate") is not True))):
                    raise ValueError("Invalid partial geometry accounting")
            elif status not in {"source_missing", "invalid_geometry_or_field"}:
                raise ValueError("Unknown field status")
            if status == "invalid_geometry_or_field" and (
                not isinstance(row.get("reason"), str) or not row["reason"]
            ):
                raise ValueError("Field failure lacks a reason")
            category = failure_category(status, row.get("reason"))
            if category is not None:
                failures[category] += 1
            statuses[status] += 1
            count += 1
    complete = bool(footer is not None and count == len(ids)
                    and footer.get("neurons") == count and footer.get("chain_sha256") == chain)
    if footer is not None and not complete:
        raise ValueError("Invalid completion footer")
    if not complete and not allow_partial:
        raise ValueError("Field computation is incomplete")
    return {"complete": complete, "processed": count, "expected": len(ids),
            "statuses": dict(statuses), "chain_sha256": chain,
            "failure_categories": dict(failures),
            "algorithm_recorded": algorithm is not None,
            "field_backend": backend, "device_info": device,
            "configuration": header["configuration"], "interpretation": header["interpretation"]}
