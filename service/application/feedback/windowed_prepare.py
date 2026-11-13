"""Prepare explicitly bounded, hash-checked source cells for CUDA replay."""

import copy
import re

from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.stimulation.experimental_gpu.events import refined_segment_events
from service.infrastructure.stimulation.experimental_gpu.hh_table import prepare_hh_table
from service.infrastructure.stimulation.experimental_gpu.prepare import prepare_registered_cell


def prepare_windowed_sources(requests, directories, simulation, *, max_cells, geometry_cache=None,
                             preparation_workers=1, preparation_executor=None):
    """Prepare source geometry and numerical provenance, without solving it.

    The caller must validate the graph, event schedule and any endpoint
    discretization before calling. Cell count is bounded, not total memory.
    """
    if (not isinstance(requests, list) or not requests or type(max_cells) is not int
            or max_cells < 1 or len(requests) > max_cells or not isinstance(simulation, dict)
            or type(preparation_workers) is not int or not 1 <= preparation_workers <= 8
            or (preparation_workers > 1 and geometry_cache is not None)
            or (preparation_executor is not None and preparation_workers == 1)
            or any(not isinstance(row, dict) or set(row) != {'id', 'expected_sha256', 'events',
                                                           'nseg_by_edge'} for row in requests)
            or any(type(row['id']) is not int or row['id'] <= 0
                   or not isinstance(row['expected_sha256'], str)
                   or not re.fullmatch('[a-f0-9]{64}', row['expected_sha256'])
                   or not isinstance(row['events'], list)
                   or not isinstance(row['nseg_by_edge'], dict) for row in requests)
            or len({row['id'] for row in requests}) != len(requests)):
        raise ValueError('Invalid bounded window source request')
    if geometry_cache is not None and any(not callable(getattr(geometry_cache, name, None))
                                          for name in ('key', 'get', 'put')):
        raise ValueError('Invalid window source geometry cache')
    fixed = {'dt_ms': simulation.get('dt_ms'), 'nseg_per_edge': 1,
             'axial_resistivity_ohm_cm': 100., 'membrane_capacitance_uf_cm2': 1.,
             'temperature_c': 23., 'initial_voltage_mv': -65.,
             'allow_disconnected': simulation.get('allow_disconnected'),
             'field_coupling': 'experimental_virtual_current',
             'solver_backend': 'experimental_numba_cuda'}
    if (type(fixed['dt_ms']) not in (int, float) or fixed['dt_ms'] not in (.025, .05)
            or type(fixed['allow_disconnected']) is not bool
            or simulation.get('nseg_per_edge') != 1):
        raise ValueError('Unsupported window source configuration')
    table, gates = prepare_hh_table()
    cells, proofs = [], {}
    parallel = None
    if preparation_workers > 1:
        from service.infrastructure.stimulation.experimental_gpu.prepare_batches import (
            prepare_registered_batch,
        )

        common = {name: simulation[name] for name in ('source_um', 'return_um', 'current_na',
            'conductivity_s_m', 'clearance_um', 'duration_ms')}
        batch = [{'body_id': request['id'], 'parameters': {
            **common, 'expected_sha256': request['expected_sha256'], 'events': request['events'],
            'nseg_by_edge': request['nseg_by_edge']}} for request in requests]
        options = {'executor': preparation_executor} if preparation_executor is not None else {}
        parallel = iter(prepare_registered_batch(batch, directories, workers=preparation_workers,
                                                 **options))
    for request in requests:
        key = None
        cell = None
        if geometry_cache is not None:
            field = {name: simulation[name] for name in ('source_um', 'return_um', 'current_na',
                'conductivity_s_m', 'clearance_um', 'duration_ms')}
            key = geometry_cache.key(request['id'], request['expected_sha256'], field, [],
                                     request['nseg_by_edge'])
            cell = geometry_cache.get(key)
        if parallel is not None:
            cell = next(parallel)
        elif cell is None:
            cell = prepare_registered_cell(request['id'], directories,
                expected_sha256=request['expected_sha256'], source_um=simulation['source_um'],
                return_um=simulation['return_um'], current_na=simulation['current_na'],
                conductivity_s_m=simulation['conductivity_s_m'],
                clearance_um=simulation['clearance_um'],
                events=request['events'], duration_ms=simulation['duration_ms'],
                nseg_by_edge=request['nseg_by_edge'])
            if geometry_cache is not None:
                geometry_cache.put(key, cell, group=request['id'])
        else:
            source = read_skeleton(request['id'], directories,
                                   expected_sha256=request['expected_sha256'])
            if source['source'] != cell['morphology_source']:
                raise ValueError('Cached source morphology provenance mismatch')
            refined_segment_events(request['events'], cell['geometry']['grid'],
                                   duration_ms=simulation['duration_ms'])
            cell['events'] = copy.deepcopy(request['events'])
        if cell['components'] > 1 and not fixed['allow_disconnected']:
            raise ValueError('Disconnected source morphology is not allowed')
        cell['initial_voltage_mv'], cell['initial_gates'] = -65., gates
        config = {**copy.deepcopy(simulation), **fixed,
                  'synaptic_events': copy.deepcopy(request['events'])}
        if request['nseg_by_edge']:
            config['nseg_by_edge'] = {str(key): value for key, value in
                                      request['nseg_by_edge'].items()}
        proofs[request['id']] = {'body_id': str(request['id']),
            'morphology_sha256': cell['morphology_sha256'],
            'morphology_source': cell['morphology_source'], 'configuration': config,
            'coordinate_frame': 'MaleCNS native EM, micrometres',
            'interpretation': 'experimental CUDA geometry; not physiological validation'}
        cells.append(cell)
    return {'cells': cells, 'provenance': proofs, 'hh_table': table}
