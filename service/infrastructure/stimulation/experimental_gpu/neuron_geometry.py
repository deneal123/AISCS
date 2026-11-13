"""Prepare cable geometry without running a NEURON time integration."""

import math

import numpy as np

from service.infrastructure.stimulation.virtual_current import adaptive_junctions

from .tree_geometry import refined_tree


def prepare_neuron_geometry(edges, nodes, counts, *, axial_resistivity, capacitance):
    """Build geometry in an isolated NEURON process and release its sections.

    ``nodes`` maps IDs to (coordinates in µm, radius in µm). Edges and
    segment counts must already come from verified morphology and endpoint
    mapping. The returned geometry does not imply biological calibration.
    """
    from neuron import h

    if (not edges or not isinstance(nodes, dict) or not isinstance(counts, dict)
            or not math.isfinite(axial_resistivity) or axial_resistivity <= 0
            or not math.isfinite(capacitance) or capacitance <= 0):
        raise ValueError('Invalid cable geometry settings')
    if any(True for _ in h.allsec()):
        raise RuntimeError('Geometry preparation requires an isolated NEURON process')
    children = [child for child, _ in edges]
    if len(set(children)) != len(children) or set(counts) != set(children):
        raise ValueError('Invalid edge or segment count mapping')
    for child, parent in edges:
        if child not in nodes or parent not in nodes or type(counts[child]) is not int:
            raise ValueError('Invalid cable node')
        if counts[child] < 1 or counts[child] % 2 != 1:
            raise ValueError('Segment counts must be positive and odd')
    try:
        starts_check = np.asarray([nodes[parent][0] for _, parent in edges], dtype=float)
        ends_check = np.asarray([nodes[child][0] for child, _ in edges], dtype=float)
        radii_check = np.asarray([(nodes[parent][1], nodes[child][1])
                                  for child, parent in edges], dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid cable coordinates or radii') from exc
    if (starts_check.shape != (len(edges), 3) or ends_check.shape != starts_check.shape
            or radii_check.shape != (len(edges), 2) or not np.isfinite(starts_check).all()
            or not np.isfinite(ends_check).all() or not np.isfinite(radii_check).all()
            or np.any(radii_check <= 0)
            or np.any(np.linalg.norm(ends_check - starts_check, axis=1) <= 0)):
        raise ValueError('Invalid cable coordinates or radii')
    sections = {}
    try:
        for child, parent in edges:
            section = h.Section(name=f'gpu_swc_{child}')
            sections[child] = section
            section.Ra = axial_resistivity
            section.cm = capacitance
            section.nseg = counts[child]
            h.pt3dclear(sec=section)
            for node in (parent, child):
                point, radius = nodes[node]
                h.pt3dadd(*point, 2 * radius, sec=section)
        root_anchor = {}
        for child, parent in edges:
            if parent in sections:
                sections[child].connect(sections[parent](1), 0)
            elif parent in root_anchor:
                sections[child].connect(sections[root_anchor[parent]](0), 0)
            else:
                root_anchor[parent] = child
        h.define_shape()
        segments = [segment for child, _ in edges for segment in sections[child]]
        edge_counts = np.fromiter((counts[child] for child in children), dtype=np.int64)
        edge_indices = np.repeat(np.arange(len(edges)), edge_counts)
        segment_indices = np.arange(len(edge_indices)) - np.repeat(
            np.cumsum(edge_counts) - edge_counts, edge_counts)
        segment_counts = edge_counts[edge_indices]
        left = segment_indices / segment_counts
        right = (segment_indices + 1) / segment_counts
        origins = starts_check[edge_indices]
        delta = ends_check[edge_indices] - origins
        starts = origins + left[:, None] * delta
        ends = origins + right[:, None] * delta
        initial_radii = radii_check[edge_indices, 0]
        radii_delta = radii_check[edge_indices, 1] - initial_radii
        radii = np.column_stack((initial_radii + left * radii_delta,
                                 initial_radii + right * radii_delta))
        grid = [(children[edge], int(index), int(count)) for edge, index, count
                in zip(edge_indices, segment_indices, segment_counts, strict=True)]
        area = np.asarray([h.area(segment.x, sec=segment.sec) for segment in segments])
        parent_resistance = [segment.ri() for segment in segments]
        child_resistance = [sections[child](1).ri() for child, _ in edges]
        junctions = adaptive_junctions(edges, counts, sections, segments,
                                       segment_resistances=parent_resistance,
                                       child_resistances=child_resistance)
        parents, conductances, segment_nodes = refined_tree(
            edges, parent_resistance, child_resistance, counts, allow_forest=True)
        return {'area': area, 'parents': parents, 'conductances': conductances,
                'segment_nodes': segment_nodes, 'junctions': junctions,
                'starts_um': starts, 'ends_um': ends, 'midpoints_um': (starts + ends) / 2,
                'endpoint_radii_um': radii, 'diameters_um': radii.sum(axis=1), 'grid': grid,
                'edge_node_ids': np.asarray([child for child, _, _ in grid], dtype=np.int64)}
    finally:
        for section in sections.values():
            h.delete_section(sec=section)
