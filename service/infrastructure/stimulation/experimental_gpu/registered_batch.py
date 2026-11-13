"""Experimental registered-morphology adapter for independent GPU cells."""

import copy
import math
import re

import numpy as np

from .batch_solver import solve_prepared_batch
from .batching import estimate_output_bytes, plan_output_batches
from .events import refined_segment_events
from .hh_table import prepare_hh_table
from .prepare import prepare_registered_cell
from .recording_adapter import attach_stimulation
from .result_adapter import as_reference_arrays


def run_registered_batch(requests, directories, stimulus_midpoint, *, source_um, return_um,
                         current_na, conductivity_s_m, clearance_um, output_budget_bytes,
                         progress=None, check_cancelled=None, recording_config=None, dt_ms=.025,
                         allow_table_clamp=False, geometry_cache=None):
    """Prepare, solve and adapt a bounded batch without a NEURON time solve.

    Every request supplies id, expected_sha256, events and optional nseg_by_edge.
    The caller is responsible for event provenance, endpoint-relocation
    evidence, pulse provenance and publication. All cells share one pulse and
    electrode pair. If supplied, recording_config is checked against the actual
    field and pulse and bound to each cell's events. This is independent-cell
    replay, not a coupled network.
    """
    if (type(dt_ms) not in (int, float) or dt_ms not in (.025, .05)
            or not isinstance(requests, list) or not requests
            or any(not isinstance(item, dict) or set(item) - {
                'id', 'expected_sha256', 'events', 'nseg_by_edge'} for item in requests)
            or any(type(item.get('id')) is not int or item['id'] <= 0 for item in requests)
            or len({item['id'] for item in requests}) != len(requests)
            or type(output_budget_bytes) is not int or output_budget_bytes < 1
            or (recording_config is not None and not isinstance(recording_config, dict))
            or (progress is not None and not callable(progress))
            or (check_cancelled is not None and not callable(check_cancelled))
            or (geometry_cache is not None and any(not callable(
                getattr(geometry_cache, name, None)) for name in ('key', 'get', 'put')))
            or isinstance(current_na, bool) or not isinstance(current_na, int | float)
            or not math.isfinite(current_na)):
        raise ValueError('Invalid registered GPU batch')
    stimulus = np.asarray(stimulus_midpoint, dtype=np.float64)
    if (stimulus.ndim != 1 or len(stimulus) < 2 or not np.isfinite(stimulus).all()
            or stimulus[0] != 0):
        raise ValueError('Invalid stimulus')
    duration = (len(stimulus) - 1) * dt_ms
    if recording_config is not None:
        if (not np.array_equal(recording_config.get('source_um'), source_um)
                or not np.array_equal(recording_config.get('return_um'), return_um)
                or recording_config.get('current_na') != current_na
                or recording_config.get('conductivity_s_m') != conductivity_s_m
                or recording_config.get('clearance_um') != clearance_um
                or recording_config.get('duration_ms') != duration):
            raise ValueError('Recording configuration does not match GPU batch')
        fixed = {'dt_ms': dt_ms, 'nseg_per_edge': 1, 'axial_resistivity_ohm_cm': 100.,
                 'membrane_capacitance_uf_cm2': 1., 'temperature_c': 23.,
                 'initial_voltage_mv': -65., 'allow_disconnected': True,
                 'field_coupling': 'experimental_virtual_current',
                 'solver_backend': 'experimental_numba_cuda'}
        if any(key in recording_config and recording_config[key] != value
               for key, value in fixed.items()):
            raise ValueError('Unsupported GPU recording configuration')
    cells = []
    for request in requests:
        if check_cancelled is not None:
            check_cancelled()
        expected = request.get('expected_sha256')
        overrides = request.get('nseg_by_edge')
        if (not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected)
                or (overrides is not None and (not isinstance(overrides, dict)
                    or any(type(key) is not int or key <= 0 or type(value) is not int
                           or value < 1 or value % 2 != 1 for key, value in overrides.items())))):
            raise ValueError('Invalid registered GPU morphology request')
        cache_key = None
        cell = None
        if geometry_cache is not None:
            cache_key = geometry_cache.key(
                request['id'], expected,
                {'source_um': list(source_um), 'return_um': list(return_um),
                 'current_na': current_na, 'conductivity_s_m': conductivity_s_m,
                 'clearance_um': clearance_um, 'duration_ms': duration},
                [], overrides or {})
            cell = geometry_cache.get(cache_key)
        if cell is None:
            cell = prepare_registered_cell(
                request['id'], directories, expected_sha256=request.get('expected_sha256'),
                source_um=source_um, return_um=return_um, current_na=current_na,
                conductivity_s_m=conductivity_s_m, clearance_um=clearance_um,
                events=request.get('events'), duration_ms=duration,
                nseg_by_edge=request.get('nseg_by_edge'))
            if geometry_cache is not None:
                geometry_cache.put(cache_key, cell, group=request['id'])
        else:
            from service.infrastructure.connectome.morphology_repository import read_skeleton

            source = read_skeleton(request['id'], directories,
                                   expected_sha256=request.get('expected_sha256'))
            if source['source'] != cell['morphology_source']:
                raise ValueError('Cached GPU morphology provenance mismatch')
            refined_segment_events(request.get('events'), cell['geometry']['grid'],
                                   duration_ms=duration)
            cell['events'] = copy.deepcopy(request['events'])
        cells.append(cell)
    table, gates = prepare_hh_table()
    for cell in cells:
        cell['initial_voltage_mv'] = -65.
        cell['initial_gates'] = gates
    for cell in cells:
        required = estimate_output_bytes(max_segments=len(cell['geometry']['grid']),
            batch_size=1, samples=len(stimulus), state_trace_cells=0)['total']
        if required > output_budget_bytes:
            raise ValueError(f"GPU output budget too small for cell {cell['id']}: "
                             f"requires {required} bytes, limit {output_budget_bytes} bytes")
    batches = plan_output_batches([len(cell['geometry']['grid']) for cell in cells],
                                  samples=len(stimulus), output_budget_bytes=output_budget_bytes)
    outputs = [None] * len(cells)
    clamped_ids = set()
    time_ms = None
    for batch_number, indexes in enumerate(batches):
        def batch_progress(done, total, offset=batch_number):
            if progress is not None:
                progress(offset * total + done, len(batches) * total)

        solved = solve_prepared_batch([cells[i] for i in indexes], stimulus, table,
                                     output_budget_bytes=output_budget_bytes,
                                     progress=batch_progress if progress else None,
                                     check_cancelled=check_cancelled, dt_ms=dt_ms,
                                     allow_table_clamp=allow_table_clamp)
        if len(solved['cells']) != len(indexes):
            raise ValueError('Incomplete GPU batch')
        if time_ms is not None and not np.array_equal(time_ms, solved['time_ms']):
            raise ValueError('GPU batches have different time grids')
        time_ms = solved['time_ms']
        clamped_ids.update(solved['table_clamped_cell_ids'])
        for index, output in zip(indexes, solved['cells'], strict=True):
            outputs[index] = output
    results = []
    for request, cell, output in zip(requests, cells, outputs, strict=True):
        if output.get('id') != cell['id']:
            raise ValueError('GPU batch order mismatch')
        arrays = as_reference_arrays(cell['geometry'], output, time_ms)
        item = {'id': cell['id'], 'morphology_sha256': cell['morphology_sha256'],
                'morphology_source': cell['morphology_source']}
        if recording_config is not None:
            config = {**copy.deepcopy(recording_config), **fixed,
                      'synaptic_events': copy.deepcopy(cell['events'])}
            if request.get('nseg_by_edge'):
                config['nseg_by_edge'] = {str(key): value
                                          for key, value in request['nseg_by_edge'].items()}
            arrays = attach_stimulation(arrays, config=config, events=cell['events'],
                                        stimulus_midpoint=stimulus,
                                        field_current_na=cell['field_current_na'],
                                        junctions=cell['geometry']['junctions'])
            item['recording_config'] = config
            import neuron

            item['provenance'] = {
                'body_id': str(cell['id']), 'morphology_sha256': cell['morphology_sha256'],
                'morphology_source': cell['morphology_source'], 'source_units': '8 nm',
                'vertices': cell['vertices'], 'components': cell['components'],
                'coordinate_frame': 'MaleCNS native EM, micrometres',
                'membrane_model': 'experimental CUDA HH; engineering reference, not calibrated',
                'stimulation_model': 'bipolar point sources; infinite homogeneous conductor',
                'fixed_parameters': {'channel_parameters': 'NEURON hh built-in defaults',
                                     'hh_kinetics': 'tabulated',
                                     'integration': 'experimental CUDA fixed step'},
                'fragment_interpretation': ('disconnected fragments remain electrically '
                                            'independent; '
                                            'connectivity is unknown' if cell['components'] > 1
                                            else 'one connected SWC component'),
                'neuron_version': neuron.__version__, 'numpy_version': np.__version__,
                'experimental_hh_table_clamped': cell['id'] in clamped_ids,
                'configuration': config,
            }
        item['arrays'] = arrays
        results.append(item)
    return results
