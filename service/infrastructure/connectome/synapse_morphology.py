"""Geometric nearest-cable candidates in the MaleCNS native EM frame.

Nearest geometry alone is not proof of a synaptic compartment or cell ownership.
"""

from __future__ import annotations

import hashlib

import numpy as np

from service.infrastructure.connectome.morphology import neurite_landmark


def _prepare_segments(swc: str):
    neurite_landmark(swc)  # validates IDs, finite coordinates and the parent graph
    nodes = {}
    for line in swc.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        nodes[int(fields[0])] = (np.asarray([float(v) * .008 for v in fields[2:5]]),
                                  int(fields[6]), float(fields[5]) * .008)
    child_ids = sorted(node for node, (_, parent, _) in nodes.items() if parent != -1)
    if not child_ids:
        raise ValueError("SWC has no cable segments")
    starts = np.stack([nodes[nodes[node][1]][0] for node in child_ids])
    ends = np.stack([nodes[node][0] for node in child_ids])
    radii = np.asarray([[nodes[nodes[node][1]][2], nodes[node][2]] for node in child_ids])
    vector = ends - starts
    length2 = np.einsum("ij,ij->i", vector, vector)
    if not np.isfinite(length2).all() or np.any(length2 <= 0):
        raise ValueError("SWC contains zero-length segments")
    return child_ids, starts, radii, vector, length2


def _nearest_prepared_segments(prepared, points_um, *, point_batch_size=16):
    if type(point_batch_size) is not int or not 1 <= point_batch_size <= 128:
        raise ValueError("Invalid point batch size")
    points = np.asarray(points_um, dtype=float)
    if points.ndim != 2 or points.shape[1:] != (3,) or not np.isfinite(points).all():
        raise ValueError("Invalid synapse coordinates")
    child_ids, starts, radii, vector, length2 = prepared
    ids, fractions, distances, local_radii = [], [], [], []
    for offset in range(0, len(points), point_batch_size):
        batch = points[offset:offset + point_batch_size]
        row = np.arange(len(batch))
        best_distance2 = np.full(len(batch), np.inf)
        exact_minimum = np.full(len(batch), np.inf)
        best_id = np.zeros(len(batch), dtype=int)
        best_fraction = np.zeros(len(batch))
        best_radius = np.zeros(len(batch))
        for segment_offset in range(0, len(child_ids), 2048):
            segment_slice = slice(segment_offset, segment_offset + 2048)
            delta = batch[:, None, :] - starts[None, segment_slice, :]
            direction = vector[segment_slice]
            fraction = np.clip(
                np.einsum("bsi,si->bs", delta, direction) / length2[segment_slice], 0, 1
            )
            residual = delta - fraction[:, :, None] * direction[None, :, :]
            distance2 = np.einsum("bsi,bsi->bs", residual, residual)
            exact_minimum = np.minimum(exact_minimum, distance2.min(axis=1))
            equal = np.isclose(distance2, exact_minimum[:, None], rtol=1e-12, atol=1e-18)
            best = np.argmax(equal, axis=1)
            local_distance2 = distance2[row, best]
            replace = (~np.isclose(best_distance2, exact_minimum, rtol=1e-12, atol=1e-18)
                       & equal.any(axis=1))
            best_distance2[replace] = local_distance2[replace]
            best_fraction[replace] = fraction[row, best][replace]
            best_id[replace] = np.asarray(child_ids)[segment_offset + best[replace]]
            selected_radii = radii[segment_offset + best[replace]]
            local_fraction = best_fraction[replace]
            best_radius[replace] = (selected_radii[:, 0] * (1 - local_fraction)
                                    + selected_radii[:, 1] * local_fraction)
        ids.extend(best_id.tolist())
        fractions.extend(best_fraction.tolist())
        distances.extend(np.sqrt(best_distance2).tolist())
        local_radii.extend(best_radius.tolist())
    if not np.isfinite(distances).all():
        raise ValueError("Non-finite synapse to cable distance")
    return {"child_node_ids": ids, "segment_fractions": fractions,
            "centerline_distances_um": distances,
            "interpolated_swc_radii_um": local_radii,
            "coordinate_frame": "MaleCNS native EM, micrometres",
            "interpretation": "nearest centerline candidates; not validated synaptic compartments"}


def nearest_swc_segments(swc: str, points_um, *, point_batch_size=16):
    """Compute exact nearest candidates in the native frame, without a cutoff.

    Equal distances choose the lowest child ID. Isolated roots are not segments.
    """
    return _nearest_prepared_segments(_prepare_segments(swc), points_um,
                                      point_batch_size=point_batch_size)


def prepare_registered_morphology(body_id, directories):
    """Snapshot and validate one registered source for a bounded multi-page scan."""
    from service.infrastructure.connectome.morphology_repository import read_skeleton

    skeleton = read_skeleton(body_id, directories)
    return skeleton, _prepare_segments(skeleton["swc"])


def registered_page_candidates(
    index, graph, body_id, direction, offset, limit, directories, *, candidate_partner_ids=None,
    prepared=None,
):
    """Map one fully checked page of graph synapses to a verified source skeleton.

    Incoming coordinates use the postsynaptic point, outgoing the presynaptic
    point. Refuse truncated or mismatching pages instead of silently producing
    an incomplete mapping. No physiological acceptance threshold is assumed.
    """
    from service.infrastructure.connectome.synapse_index import registered_page_pairs

    page = registered_page_pairs(index, graph, body_id, direction, offset, limit, all_pairs=True)
    if page["truncated"] or not page["counts_match"]:
        raise ValueError("Synapse page is truncated or inconsistent with registered graph")
    skeleton, geometry = prepared if prepared is not None else prepare_registered_morphology(
        body_id, directories
    )
    if skeleton["body_id"] != str(body_id):
        raise ValueError("Prepared morphology does not match neuron")
    suffix, partner_key = ("pre", "body_post") if direction == "outgoing" else ("post", "body_pre")
    selection_hash = None
    if candidate_partner_ids is not None:
        if (not isinstance(candidate_partner_ids, set)
                or any(type(item) is not int or item <= 0 for item in candidate_partner_ids)):
            raise ValueError("Invalid candidate partner selection")
        selection_hash = hashlib.sha256(
            "".join(f"{item}\n" for item in sorted(candidate_partner_ids)).encode("ascii")
        ).hexdigest()
    selected_rows = [row for row in page["pairs"] if candidate_partner_ids is None
                     or row[partner_key] in candidate_partner_ids]
    source_coordinates = [
        [row[f"{axis}_{suffix}"] for axis in "xyz"] for row in selected_rows
    ]
    points = np.asarray(source_coordinates, dtype=float).reshape(-1, 3) * .008
    mapping = _nearest_prepared_segments(geometry, points)
    candidates = [
        {"partner_id": str(row[partner_key]), "source_position_8nm": position,
         **({"presynaptic_position_8nm": [row[f"{axis}_pre"] for axis in "xyz"]}
            if direction == "incoming" and all(f"{axis}_pre" in row for axis in "xyz") else {}),
         "child_node_id": child, "segment_fraction": fraction,
         "centerline_distance_um": distance, "interpolated_radius_um": radius}
        for row, position, child, fraction, distance, radius in zip(
            selected_rows, source_coordinates, mapping["child_node_ids"],
            mapping["segment_fractions"], mapping["centerline_distances_um"],
            mapping["interpolated_swc_radii_um"], strict=True,
        )
    ]
    return {"body_id": str(body_id), "direction": direction, "offset": offset,
            "next_offset": page["graph_next_offset"], "source_md5": page["source_md5"],
            "morphology_sha256": skeleton["sha256"],
            "graph_manifest_sha256": page["graph_manifest_sha256"],
            "source_coordinate_frame": page["coordinate_frame"],
            "partner_selection_sha256": selection_hash,
            "selection": "all partners" if selection_hash is None else "specified partner IDs",
            "interpretation": mapping["interpretation"], "candidates": candidates}


def merge_candidate_pages(pages, *, require_complete=True):
    """Join contiguous candidate pages without presenting partial coverage as full."""
    if type(require_complete) is not bool or not isinstance(pages, list) or not pages:
        raise ValueError("Invalid candidate pages")
    first = pages[0]
    keys = ("body_id", "direction", "source_md5", "morphology_sha256",
            "graph_manifest_sha256", "source_coordinate_frame")
    if (not isinstance(first, dict) or first.get("offset") != 0
            or any(not isinstance(first.get(key), str) or not first[key] for key in keys)):
        raise ValueError("Candidate pages must start at zero with provenance")
    candidates, seen_partners = [], set()
    previous_next = 0
    for page_index, page in enumerate(pages):
        if (not isinstance(page, dict) or any(page.get(key) != first[key] for key in keys)
                or page.get("partner_selection_sha256") != first.get("partner_selection_sha256")
                or page.get("selection") != first.get("selection")
                or (page_index > 0 and previous_next is None)
                or type(page.get("offset")) is not int or page.get("offset") != previous_next
                or "next_offset" not in page or not isinstance(page.get("candidates"), list)):
            raise ValueError("Candidate pages are incompatible or noncontiguous")
        page_partners = set()
        for candidate in page["candidates"]:
            if not isinstance(candidate, dict) or not isinstance(candidate.get("partner_id"), str):
                raise ValueError("Invalid candidate partner")
            page_partners.add(candidate["partner_id"])
        if seen_partners & page_partners:
            raise ValueError("Candidate partner appears on multiple pages")
        seen_partners.update(page_partners)
        candidates.extend(page["candidates"])
        previous_next = page.get("next_offset")
        if previous_next is not None and (type(previous_next) is not int
                                          or previous_next <= page["offset"]):
            raise ValueError("Invalid next page offset")
    complete = previous_next is None
    if require_complete and not complete:
        raise ValueError("Candidate pages do not cover all graph edges")
    return {**{key: first[key] for key in keys}, "offset": 0,
            "next_offset": previous_next, "complete_graph_edge_coverage": complete,
            "partner_selection_sha256": first.get("partner_selection_sha256"),
            "selection": first.get("selection"),
            "pages": len(pages), "candidates": candidates,
            "interpretation": "nearest centerline candidates; not validated synaptic compartments"}


def registered_incoming_candidates_single_pass(
    index, graph, body_id, directories, *, candidate_partner_ids, progress=None,
):
    """Verify all incoming edge counts in one source scan and map active pairs."""
    from service.infrastructure.connectome.neighbors import incoming

    if (not isinstance(candidate_partner_ids, set)
            or any(type(value) is not int or value <= 0 for value in candidate_partner_ids)):
        raise ValueError("Invalid candidate partner selection")
    if index.manifest["ids_sha256"] != graph.provenance["array_sha256"]["ids.npy"]:
        raise ValueError("Synapse index and graph neuron IDs differ")
    edges = incoming(graph, body_id, 0, len(graph.posts))["items"]
    partners = [int(item["source_id"]) for item in edges]
    scan = index.scan_incoming(body_id, partners, candidate_partner_ids)
    if any(scan["counts"][int(edge["source_id"])] != edge["synapse_count"] for edge in edges):
        raise ValueError("Synapse page is truncated or inconsistent with registered graph")
    skeleton, geometry = prepare_registered_morphology(body_id, directories)
    if skeleton["body_id"] != str(body_id):
        raise ValueError("Prepared morphology does not match neuron")
    page_count = max(1, (len(edges) + 19) // 20)
    page_by_partner = {partner: number // 20 for number, partner in enumerate(partners)}
    buckets = [[] for _ in range(page_count)]
    for row in scan["pairs"]:
        buckets[page_by_partner[row["body_pre"]]].append(row)
    rows = [row for bucket in buckets for row in bucket]
    positions = [[row[f"{axis}_post"] for axis in "xyz"] for row in rows]
    points = np.asarray(positions, dtype=float).reshape(-1, 3) * .008
    mapped = _nearest_prepared_segments(geometry, points)
    candidates = [
        {"partner_id": str(row["body_pre"]), "source_position_8nm": position,
         **({"presynaptic_position_8nm": [row[f"{axis}_pre"] for axis in "xyz"]}
            if all(f"{axis}_pre" in row for axis in "xyz") else {}),
         "child_node_id": child, "segment_fraction": fraction,
         "centerline_distance_um": distance, "interpolated_radius_um": radius}
        for row, position, child, fraction, distance, radius in zip(
            rows, positions, mapped["child_node_ids"], mapped["segment_fractions"],
            mapped["centerline_distances_um"], mapped["interpolated_swc_radii_um"], strict=True,
        )
    ]
    if progress is not None:
        for number in range(page_count):
            offset = number * 20
            progress(number + 1, offset, offset + 20 if number + 1 < page_count else None)
    selection_hash = hashlib.sha256(
        "".join(f"{value}\n" for value in sorted(candidate_partner_ids)).encode("ascii")
    ).hexdigest()
    return {"body_id": str(body_id), "direction": "incoming", "source_md5": scan["source_md5"],
            "morphology_sha256": skeleton["sha256"],
            "graph_manifest_sha256": graph.provenance["manifest_sha256"],
            "source_coordinate_frame": scan["coordinate_frame"], "offset": 0,
            "next_offset": None, "complete_graph_edge_coverage": True,
            "partner_selection_sha256": selection_hash, "selection": "specified partner IDs",
            "pages": page_count, "candidates": candidates,
            "interpretation": "nearest centerline candidates; not validated synaptic compartments"}
