"""Contracts and validation for native field and contact geometry requests."""

from __future__ import annotations

import math
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

StrictFloat = Annotated[float, Field(strict=True)]


class NativeFieldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source_um: tuple[StrictFloat, StrictFloat, StrictFloat]
    return_um: tuple[StrictFloat, StrictFloat, StrictFloat]
    current_na: float = Field(strict=True)
    conductivity_s_m: float = Field(strict=True, gt=0)
    clearance_um: float = Field(strict=True, gt=0)


class SpatialCandidatesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source_um: tuple[StrictFloat, StrictFloat, StrictFloat]
    return_um: tuple[StrictFloat, StrictFloat, StrictFloat]
    radius_um: float = Field(strict=True, ge=0)
    electrode_um: tuple[StrictFloat, StrictFloat, StrictFloat] | None = None
    reference_um: tuple[StrictFloat, StrictFloat, StrictFloat] | None = None

    @model_validator(mode="after")
    def complete_recording_pair(self):
        if (self.electrode_um is None) != (self.reference_um is None):
            raise ValueError("Both recording contacts are required")
        return self


class ContactScreenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source_um: tuple[StrictFloat, StrictFloat, StrictFloat]
    return_um: tuple[StrictFloat, StrictFloat, StrictFloat]
    electrode_um: tuple[StrictFloat, StrictFloat, StrictFloat]
    reference_um: tuple[StrictFloat, StrictFloat, StrictFloat]
    clearance_um: float = Field(strict=True, gt=0)


class ContactPositionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    positions_um: list[tuple[StrictFloat, StrictFloat, StrictFloat]] = Field(
        min_length=1, max_length=64
    )
    clearance_um: float = Field(strict=True, gt=0)


def valid_contact_screen(
    result, request: ContactScreenRequest | ContactPositionsRequest, expected: str, neurons: int
):
    count = len(request.positions_um) if isinstance(request, ContactPositionsRequest) else 4
    if (not isinstance(result, dict) or not isinstance(expected, str) or not expected
            or type(neurons) is not int or neurons <= 0
            or result.get("manifest_sha256") != expected
            or result.get("coordinate_frame") != "male-cns-v1.0-native-um"
            or result.get("interpretation") != ("conservative SWC snapshot screening; "
                                               "not tissue anatomy or activation")
            or result.get("configuration") != request.model_dump(mode="json")
            or type(result.get("indexed")) is not int or result["indexed"] != neurons
            or type(result.get("examined")) is not int or not 0 <= result["examined"] <= neurons
            or not isinstance(result.get("potential_intersections"), list)
            or len(result["potential_intersections"]) > result["examined"]):
        return False
    seen = set()
    for row in result["potential_intersections"]:
        if (not isinstance(row, dict) or set(row) != {"body_id", "source_sha256",
                                                       "contact_indices",
                                                       "conservative_clearance_um"}):
            return False
        body, sha, indices, values = (row[key] for key in ("body_id", "source_sha256",
                                                           "contact_indices",
                                                           "conservative_clearance_um"))
        if (type(body) is not int or not 0 < body < 2**63 or body in seen
                or not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha)
                or not isinstance(indices, list) or not indices
                or not isinstance(values, list) or len(values) != count
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in values)
                or any(type(index) is not int for index in indices)
                or indices != [i for i, value in enumerate(values)
                               if value <= request.clearance_um]):
            return False
        seen.add(body)
    return True


def valid_spatial_candidates(result, request: SpatialCandidatesRequest, expected: str,
                             expected_neurons: int) -> bool:
    if not isinstance(result, dict):
        return False
    try:
        configuration = SpatialCandidatesRequest.model_validate(result.get("configuration"))
        rows = result["candidates"]
        if (configuration != request or result.get("manifest_sha256") != expected
                or result.get("coordinate_frame") != "male-cns-v1.0-native-um"
                or result.get("interpretation") != (
                    "centerline proximity in indexed snapshot; not excitation")
                or type(expected_neurons) is not int or expected_neurons <= 0
                or type(result.get("indexed")) is not int or result["indexed"] != expected_neurons
                or type(result.get("bounding_box_matches")) is not int
                or not isinstance(rows, list)
                or not len(rows) <= result["bounding_box_matches"] <= result["indexed"]):
            return False
        previous, seen = None, set()
        for row in rows:
            if not isinstance(row, dict):
                return False
            body, distance = row.get("body_id"), row.get("distance_um")
            fraction, isolated = row.get("edge_fraction"), row.get("isolated_root")
            child, contact = row.get("child_node_id"), row.get("contact")
            geometry = row.get("geometry")
            clearance = row.get("conservative_clearance_um")
            recording_clearance = row.get("recording_clearance_um")
            if (type(body) is not int or not 0 < body < 2**63 or body in seen
                    or type(distance) not in (int, float) or not math.isfinite(distance)
                    or not 0 <= distance <= request.radius_um
                    or type(fraction) not in (int, float) or not math.isfinite(fraction)
                    or not 0 <= fraction <= 1 or type(contact) is not int or contact not in (0, 1)
                    or type(isolated) is not bool
                    or (isolated and child is not None)
                    or (not isolated and (type(child) is not int or child <= 0))
                    or not isinstance(geometry, dict)
                    or any(type(geometry.get(key)) is not int or geometry[key] < 0 for key in (
                        "components", "isolated_roots", "zero_length_edges",
                        "nonpositive_radius_edges"))
                    or geometry["components"] < 1
                    or geometry["isolated_roots"] > geometry["components"]
                    or (isolated and geometry["isolated_roots"] == 0)
                    or not isinstance(clearance, list) or len(clearance) != 2
                    or any(type(value) not in (int, float) or not math.isfinite(value)
                           for value in clearance)
                    or (request.electrode_um is not None and (
                        not isinstance(recording_clearance, list) or len(recording_clearance) != 2
                        or any(type(value) not in (int, float) or not math.isfinite(value)
                               for value in recording_clearance)))
                    or (request.electrode_um is None and recording_clearance is not None)
                    or not isinstance(row.get("source_sha256"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", row["source_sha256"])):
                return False
            ordering = (distance, body)
            if previous is not None and ordering < previous:
                return False
            previous = ordering
            seen.add(body)
        return True
    except (KeyError, TypeError, ValueError):
        return False


def valid_native_field(result, request: NativeFieldRequest) -> bool:
    """Reject mismatched field inputs and malformed per-vertex data."""
    if not isinstance(result, dict):
        return False
    try:
        actual = NativeFieldRequest.model_validate(result.get("configuration"))
    except ValueError:
        return False
    if (actual != request or result.get("medium") != "infinite-homogeneous-isotropic"
            or result.get("interpretation") != "field-only; not excitation or tissue-calibrated"
            or not isinstance(result.get("source_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", result["source_sha256"])):
        return False
    ids, values = result.get("vertex_ids"), result.get("potential_mv")
    curvature_ids = result.get("curvature_vertex_ids")
    curvature = result.get("curvature_mv_per_um2")
    if (not isinstance(ids, list) or not ids or not isinstance(values, list)
            or not isinstance(curvature_ids, list) or not isinstance(curvature, list)
            or len(ids) != len(values) or len(curvature_ids) != len(curvature)
            or any(type(value) is not int or value <= 0 for value in ids + curvature_ids)
            or len(set(ids)) != len(ids) or len(set(curvature_ids)) != len(curvature_ids)
            or not set(curvature_ids).issubset(ids)
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   for value in values + curvature)):
        return False
    return True
