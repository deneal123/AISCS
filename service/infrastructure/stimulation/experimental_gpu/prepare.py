"""Prepare a verified registered morphology for the experimental CUDA solver."""

import re

import numpy as np

from service.infrastructure.connectome.morphology import _validated_nodes
from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.stimulation.point_field import (
    bipolar_potential_mv,
    validate_segment_clearance,
)
from service.infrastructure.stimulation.virtual_current import junction_currents

from .events import refined_segment_events
from .neuron_geometry import prepare_neuron_geometry


def prepare_registered_cell(body_id, directories, *, expected_sha256, source_um, return_um,
                            current_na, conductivity_s_m, clearance_um, events, duration_ms,
                            nseg_by_edge=None, axial_resistivity=100., capacitance=1.):
    """Return verified geometry and field for a source morphology.

    Call in an isolated NEURON process. Endpoint relocations, if any, must be
    performed and documented by the caller before invoking this function.
    The receipt does not establish physiological or clinical validity.
    """
    if not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('A verified morphology SHA-256 is required')
    source = read_skeleton(body_id, directories, expected_sha256=expected_sha256)
    swc = source.pop('swc')
    validated = _validated_nodes(swc, include_radii=True)
    del swc
    components = sum(parent == -1 for _, parent, _, _ in validated.values())
    nodes = {body: (np.asarray(xyz), radius)
             for body, (xyz, _parent, _kind, radius) in validated.items()}
    edges = [(body, parent) for body, (_, parent, _, _) in validated.items() if parent != -1]
    del validated
    return _prepare_cable_inputs(body_id, nodes, edges, components, source,
        source_um=source_um, return_um=return_um, current_na=current_na,
        conductivity_s_m=conductivity_s_m, clearance_um=clearance_um, events=events,
        duration_ms=duration_ms, nseg_by_edge=nseg_by_edge,
        axial_resistivity=axial_resistivity, capacitance=capacitance)


def prepare_cached_cell(entry, *, body_id, expected_sha256, source_um, return_um, current_na,
                        conductivity_s_m, clearance_um, events, duration_ms, nseg_by_edge=None,
                        axial_resistivity=100., capacitance=1.):
    """Prepare an entry authenticated by the cache reader; experimental only.

    The caller must first authenticate its manifest, source index and chunk.
    This path does not read or verify current SWC files and is not a service API.
    """
    from .cached_geometry import cached_cable_inputs

    nodes, edges, components = cached_cable_inputs(entry, body_id=body_id,
                                                   expected_sha256=expected_sha256)
    return _prepare_cable_inputs(body_id, nodes, edges, components, entry['skeleton'],
        source_um=source_um, return_um=return_um, current_na=current_na,
        conductivity_s_m=conductivity_s_m, clearance_um=clearance_um, events=events,
        duration_ms=duration_ms, nseg_by_edge=nseg_by_edge,
        axial_resistivity=axial_resistivity, capacitance=capacitance)


def _prepare_cable_inputs(body_id, nodes, edges, components, source, *, source_um, return_um,
                          current_na, conductivity_s_m, clearance_um, events, duration_ms,
                          nseg_by_edge, axial_resistivity, capacitance):
    overrides = {} if nseg_by_edge is None else nseg_by_edge
    if (not isinstance(overrides, dict)
            or not set(overrides).issubset({child for child, _ in edges})
            or any(type(child) is not int or type(count) is not int or count < 1 or count % 2 != 1
                   for child, count in overrides.items())):
        raise ValueError('Invalid segment count overrides')
    counts = {child: overrides.get(child, 1) for child, _ in edges}
    grid = [(child, segment, counts[child]) for child, _ in edges
            for segment in range(counts[child])]
    refined_segment_events(events, grid, duration_ms=duration_ms)
    validate_segment_clearance(
        np.asarray([nodes[parent][0] for _, parent in edges]),
        np.asarray([nodes[child][0] for child, _ in edges]), [source_um, return_um], clearance_um,
        np.asarray([[nodes[parent][1], nodes[child][1]] for child, parent in edges]))
    geometry = prepare_neuron_geometry(edges, nodes, counts, axial_resistivity=axial_resistivity,
                                       capacitance=capacitance)
    if geometry['grid'] != grid:
        raise ValueError('Prepared segment ordering mismatch')
    field = bipolar_potential_mv(geometry['midpoints_um'], source_um, return_um, current_na,
                                 conductivity_s_m, clearance_um=clearance_um)
    return {'id': body_id, 'geometry': geometry,
            'field_current_na': junction_currents(field, geometry['junctions']),
            'field_mv': field,
            'events': events, 'morphology_sha256': source['sha256'],
            'morphology_source': source['source'], 'vertices': len(nodes), 'components': components}
