"""Conservative contact preflight for experimental fragment executions."""

from __future__ import annotations

import os
import re
from pathlib import Path

from service.infrastructure.stimulation.contacts.screen import screen_contacts


def check_fragment_contacts(config, graph, directories):
    """Reject incomplete indexes or a possible contact/SWC intersection.

    This does not validate tissue geometry, electrode shape or anatomy.
    """
    if graph.provenance.get("manifest_sha256") != config.graph_manifest_sha256:
        raise ValueError("Requested graph does not match registered graph")
    names = (
        "GENERATOR_MORPHOLOGY_BOUNDS_DB",
        "GENERATOR_MORPHOLOGY_BOUNDS_AUDIT",
        "GENERATOR_MORPHOLOGY_RADIUS_DB",
        "GENERATOR_MORPHOLOGY_RADIUS_AUDIT",
        "GENERATOR_MORPHOLOGY_SEGMENT_DB",
        "GENERATOR_MORPHOLOGY_SEGMENT_AUDIT",
    )
    values = [os.environ.get(name, "") for name in names]
    if any(not value or not Path(value).is_file() for value in values):
        raise ValueError("Verified contact-screen indexes are unavailable")
    sim = config.simulation
    report = screen_contacts(
        *(Path(value) for value in values[:4]),
        graph.ids,
        config.graph_manifest_sha256,
        directories,
        [sim.source_um, sim.return_um, sim.electrode_um, sim.reference_um],
        sim.clearance_um,
        segment_index=Path(values[4]),
        segment_audit=Path(values[5]),
        workers=1,
    )
    flagged = report.get("potential_intersections")
    if not isinstance(flagged, list) or report.get("indexed") != len(graph.ids):
        raise ValueError("Incomplete contact-screen result")
    if flagged:
        counts = [0, 0, 0, 0]
        for row in flagged:
            indices = row.get("contact_indices") if isinstance(row, dict) else None
            if (
                not isinstance(indices, list)
                or not indices
                or any(type(index) is not int or not 0 <= index < 4 for index in indices)
                or len(set(indices)) != len(indices)
            ):
                raise ValueError("Invalid contact-screen intersection")
            for index in indices:
                counts[index] += 1
        details = ", ".join(
            f"{name}={count}"
            for name, count in zip(("STIM+", "STIM−", "E1", "REF"), counts, strict=True)
            if count
        )
        raise ValueError(
            f"Contact clearance not established: {len(flagged)} potential SWC intersections "
            f"({details})"
        )
    return report


def fragment_contact_receipt(config, graph, report, *, allow_legacy=False):
    """Bind the successful screening summary to the requested coordinates."""
    if (
        graph.provenance.get("manifest_sha256") != config.graph_manifest_sha256
        or not isinstance(report, dict)
        or type(report.get("indexed")) is not int
        or report["indexed"] != graph.size
        or type(report.get("examined")) is not int
        or not 0 <= report["examined"] <= graph.size
        or report.get("potential_intersections") != []
    ):
        raise ValueError("Invalid successful contact-screen summary")
    hashes = report.get("index_sha256")
    if hashes is None and allow_legacy is True:
        pass
    elif (
        not isinstance(hashes, dict)
        or set(hashes) != {"bounds", "radii", "segments"}
        or any(
            not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
            for value in hashes.values()
        )
    ):
        raise ValueError("Missing or invalid contact-screen index hashes")
    sim = config.simulation
    receipt = {
        "configuration_sha256": config.digest(),
        "graph_sha256": config.graph_manifest_sha256,
        "contacts_um": [
            list(point)
            for point in (sim.source_um, sim.return_um, sim.electrode_um, sim.reference_um)
        ],
        "clearance_um": sim.clearance_um,
        "indexed": report["indexed"],
        "examined": report["examined"],
        "potential_intersections": 0,
        "scope": "point contacts against registered SWC; tissue and electrode shape unvalidated",
    }
    if hashes is not None:
        receipt["index_sha256"] = dict(hashes)
    return receipt
