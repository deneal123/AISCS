"""Prepare explicitly refined cells inside an authenticated population replay."""

from dataclasses import replace

import numpy as np

from service.infrastructure.connectome.morphology import _validated_nodes
from service.infrastructure.connectome.morphology_repository import read_skeleton

from .fast_cable import CACHE_RECORD, prepare_chunk
from .fast_prepare import cells_from_chunk
from .grid_contract import grid_configuration
from .prepare import prepare_registered_cell


def refined_cell_transform(grids, directories, params, *, duration_ms, capture_original=None):
    """Build selected cells from their verified SWC; all other cells pass through.

    ``capture_original`` must persist source geometry before subdivision when
    source diagnostics require original edge coordinates. The caller owns grid
    policy, paired-run consistency and event-position verification.
    """
    if (not isinstance(grids, dict) or params.nseg != 1
            or type(duration_ms) is not int or duration_ms < 1
            or (capture_original is not None and not callable(capture_original))):
        raise ValueError('Invalid refined population configuration')
    frozen = {}
    for body, counts in grids.items():
        if (type(body) is not int or body <= 0 or not isinstance(counts, dict)
                or any(type(edge) is not int or edge <= 0 or type(count) is not int
                       or count < 1 or count % 2 != 1 for edge, count in counts.items())):
            raise ValueError('Invalid refined population grid')
        frozen[body] = counts.copy()

    def transform(cell):
        body = cell['id']
        if body not in frozen or not frozen[body]:
            return cell
        if capture_original is not None:
            capture_original([cell])
        refined = prepare_registered_cell(body, directories,
            expected_sha256=cell['morphology_sha256'], source_um=params.source_um,
            return_um=params.return_um, current_na=params.current_na,
            conductivity_s_m=params.conductivity_s_m, clearance_um=params.clearance_um,
            events=[], duration_ms=duration_ms, nseg_by_edge=frozen[body],
            axial_resistivity=params.axial_resistivity, capacitance=params.capacitance)
        geometry = refined['geometry']
        config = grid_configuration(geometry['grid'], geometry['edge_node_ids'])
        expected = {str(edge): count for edge, count in frozen[body].items() if count != 1}
        if config['nseg_by_edge'] != expected:
            raise ValueError('Refined population grid mismatch')
        geometry['segment_index'] = np.asarray([entry[1] for entry in geometry['grid']],
                                               dtype=np.int32)
        refined['initial_voltage_mv'] = cell['initial_voltage_mv']
        refined['initial_gates'] = cell['initial_gates']
        return refined

    return transform


def uniform_refined_cell(body, directories, *, expected_sha256, params, nseg):
    """Rebuild one verified morphology with uniform subdivision, without NEURON.

    Any target event relocation must be re-audited on this exact uniform grid.
    """
    if type(nseg) is not int or nseg < 1 or nseg % 2 != 1:
        raise ValueError('Invalid uniform segment count')
    source = read_skeleton(body, directories, expected_sha256=expected_sha256)
    nodes = _validated_nodes(source['swc'], include_radii=True)
    indices = {node: index for index, node in enumerate(nodes)}
    records = np.array([(*xyz, radius, indices[parent] if parent != -1 else -1, node)
                        for node, (xyz, parent, _kind, radius) in nodes.items()],
                       dtype=CACHE_RECORD)
    result = prepare_chunk(records, np.array([0], dtype=np.int64),
        np.array([len(records)], dtype=np.int64), replace(params, nseg=nseg),
        bodies=[body], store_bounds=True)
    if len(result.error_codes) != 1 or int(result.error_codes[0]) != 0:
        raise ValueError('Refined population morphology preparation failed')
    cell = cells_from_chunk(result, sources={body: expected_sha256})[0]
    geometry = cell['geometry']
    geometry['grid'] = [(int(edge), int(segment), nseg)
                        for edge, segment in zip(geometry['edge_node_ids'],
                                                 geometry['segment_index'], strict=True)]
    grid_configuration(geometry['grid'], geometry['edge_node_ids'])
    return cell


def uniform_cell_transform(counts, directories, params, *, capture_original=None):
    """Create a population transform for independently audited uniform grids."""
    if (not isinstance(counts, dict) or params.nseg != 1
            or any(type(body) is not int or body <= 0 or type(count) is not int
                   or count < 1 or count % 2 != 1 for body, count in counts.items())
            or (capture_original is not None and not callable(capture_original))):
        raise ValueError('Invalid uniform population grids')
    frozen = counts.copy()

    def transform(cell):
        body = cell['id']
        if frozen.get(body, 1) == 1:
            return cell
        if capture_original is not None:
            capture_original([cell])
        return uniform_refined_cell(body, directories, expected_sha256=cell['morphology_sha256'],
                                    params=params, nseg=frozen[body])

    return transform
