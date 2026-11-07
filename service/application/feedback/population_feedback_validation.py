"""Validate a coupled population result before it can be persisted or displayed.

The source archive must already have been verified by load_verified_fragment_population.
This checks internal consistency; it does not authenticate results or validate physiology.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np

from service.domain.contracts.fragment_population_contract import FragmentPopulationConfig
from service.infrastructure.stimulation.feedback_discretization import (
    verify_feedback_discretization,
)
from service.infrastructure.stimulation.fragment_sparse_delta import encode_sparse_delta
from service.infrastructure.stimulation.population_feedback_checkpoint import validate_checkpoint


def validate_population_feedback(result, graph, source, *, parameters, allow_partial_geometry,
                                 discretization_context=None):
    if not isinstance(result, dict) or not isinstance(source, dict):
        raise ValueError('Invalid coupled result')
    has_history_receipts = 'discretization_receipts' in result
    has_final_receipt = 'discretization_receipt' in result
    if has_history_receipts or has_final_receipt:
        if not isinstance(result.get('schedule'), dict) or not isinstance(
                result.get('iterations'), list):
            raise ValueError('Missing discretization schedule or iteration history')
        if not isinstance(discretization_context, dict) or set(discretization_context) != {
                'index', 'directories', 'policy'}:
            raise ValueError('Discretization receipts are not supported without verified context')
        index = discretization_context['index']
        policy = discretization_context['policy']
        index_manifest = getattr(index, 'manifest', None)
        provenance = getattr(graph, 'provenance', {})
        arrays = provenance.get('array_sha256', {}) if isinstance(provenance, dict) else {}
        if (not isinstance(index_manifest, dict) or not isinstance(policy, dict)
                or not isinstance(arrays, dict) or not arrays.get('ids.npy')
                or index_manifest.get('ids_sha256') != arrays['ids.npy']
                or index_manifest.get('source_md5') != policy.get('expected_source_md5')):
            raise ValueError('Discretization index and graph identity mismatch')
        if has_history_receipts:
            receipts = result['discretization_receipts']
            if (not isinstance(receipts, list) or not receipts
                    or len(receipts) != len(result.get('iterations', []))):
                raise ValueError('Missing iteration discretization receipts')
            receipt = receipts[-1]
            if has_final_receipt and result['discretization_receipt'] != receipt:
                raise ValueError('Conflicting final discretization receipt')
        else:
            receipt = result['discretization_receipt']
        verify_feedback_discretization(result['schedule'], receipt, index,
                                       discretization_context['directories'], policy=policy)
    elif discretization_context is not None:
        raise ValueError('Discretization context without receipt')
    metadata, manifest = source.get('metadata'), source.get('manifest')
    if not isinstance(metadata, dict) or not isinstance(manifest, dict):
        raise ValueError('Verified source metadata required')
    config = FragmentPopulationConfig.model_validate(metadata['configuration'])
    source_schedules = metadata.get('schedules', [])
    if (not isinstance(source_schedules, list)
            or any(not isinstance(row, dict)
                   or not isinstance(row.get('unresolved_geometry', []), list)
                   for row in source_schedules)
            or (config.allow_partial_geometry is True
                and len(source_schedules) != len(config.source_ids))):
        raise ValueError('Missing partial source geometry evidence')
    source_unresolved = sum(len(row.get('unresolved_geometry', [])) for row in source_schedules)
    if (manifest.get('configuration_sha256') != config.digest()
            or manifest.get('graph_sha256') != config.graph_manifest_sha256
            or graph.provenance.get('manifest_sha256') != config.graph_manifest_sha256):
        raise ValueError('Coupled input identity mismatch')
    status = result.get('status')
    if status not in ('converged', 'converged_partial'):
        raise ValueError('Unconverged coupled result cannot be published')
    if result.get('feedback_alignment') != 'schedule_matches_last_replay':
        raise ValueError('Coupled schedule and recording are not aligned')
    physical, network, schedule = (result.get('physical_source_output'), result.get('network'),
                                   result.get('schedule'))
    if not all(isinstance(value, dict) for value in (physical, network, schedule)):
        raise ValueError('Missing coupled result components')
    diagnostics = {int(row['body_id']): row for row in metadata['diagnostics']}
    ids = config.source_ids
    hashes = {body: diagnostics[body]['morphology_sha256'] for body in ids}
    if (physical.get('source_ids') != ids
            or physical.get('graph_sha256') != config.graph_manifest_sha256
            or physical.get('source_configuration_sha256') != config.digest()
            or physical.get('source_morphology_sha256') != hashes
            or physical.get('threshold_mv') != config.threshold_mv
            or network.get('forced_cell_ids') != ids
            or schedule.get('source_ids') != ids
            or schedule.get('graph_sha256') != config.graph_manifest_sha256
            or not isinstance(schedule.get('unresolved'), list)
            or (config.allow_partial_geometry is True
                and (type(physical.get('source_unresolved_graph_pairs')) is not int
                     or physical['source_unresolved_graph_pairs'] != source_unresolved))
            or (config.allow_partial_geometry is not True
                and 'source_unresolved_graph_pairs' in physical)
            or (status == 'converged_partial') != bool(schedule['unresolved'] or source_unresolved)
            or (bool(schedule['unresolved'] or source_unresolved) and not allow_partial_geometry)):
        raise ValueError('Coupled population identity mismatch')
    history = result.get('iterations')
    if not isinstance(history, list) or not history:
        raise ValueError('Missing coupled iteration history')
    signature = hashlib.sha256(json.dumps(
        {'events': schedule['events_by_target'], 'unresolved': schedule['unresolved']},
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if history[-1].get('schedule_sha256') != signature:
        raise ValueError('Coupled schedule checksum mismatch')
    recording = result['recording']
    names = ('time_ms', 'neural_uv', 'stimulus_artifact_uv', 'stimulus_fraction', 'total_uv')
    state = {'format': 'population-feedback-checkpoint-v1', 'configuration_sha256': config.digest(),
             'graph_sha256': config.graph_manifest_sha256, 'source_ids': ids,
             'run_identity': '0' * 64, 'allow_partial_geometry': allow_partial_geometry,
             'parameters': json.loads(json.dumps(parameters)), 'history': history,
             'local': {str(key): rows for key, rows in
                       physical['candidate_events_by_source'].items()},
             'edges': physical['edge_events'],
             'recording': {'cells': recording['cells'],
                           **{name: np.asarray(recording[name]).tolist() for name in names}}}
    validate_checkpoint(state, config=config, diagnostics=diagnostics, parameters=parameters,
                        allow_partial_geometry=allow_partial_geometry, run_identity='0' * 64)
    indices, times, counts = (np.asarray(network.get(name)) for name in
                              ('spike_neurons', 'spike_times_ms', 'counts'))
    network_meta = network.get('metadata')
    forced = np.searchsorted(graph.ids, ids)
    if (not isinstance(network_meta, dict)
            or network_meta.get('graph') != graph.provenance
            or network_meta.get('seed') != config.seed
            or network_meta.get('duration_ms') != config.simulation.duration_ms
            or indices.ndim != 1 or indices.dtype.kind not in 'iu' or times.shape != indices.shape
            or times.dtype.kind not in 'iuf' or not np.isfinite(times).all()
            or np.any(indices < 0) or np.any(indices >= graph.size)
            or np.isin(indices, forced).any() or np.any(times < 1)
            or np.any(times > config.simulation.duration_ms) or np.any(times != np.floor(times))
            or np.any(times[1:] < times[:-1]) or counts.shape != (graph.size,)
            or counts.dtype.kind not in 'iu'
            or not np.array_equal(counts, np.bincount(indices, minlength=graph.size))):
        raise ValueError('Invalid coupled network spikes')
    for name in ('final_voltage_relative_mv', 'final_synaptic_drive_mv'):
        values = np.asarray(network.get(name))
        if (values.shape != (graph.size,) or values.dtype.kind != 'f'
                or not np.isfinite(values).all()):
            raise ValueError('Invalid coupled network state')
    sparse = network.get('sparse_delta')
    if not isinstance(sparse, dict) or sparse.get('status') != 'recorded':
        raise ValueError('Full graph response is not available')
    encode_sparse_delta(sparse, graph=graph, source_ids=ids,
                        duration_ms=int(config.simulation.duration_ms),
                        configuration_sha256=config.digest())
    return result
