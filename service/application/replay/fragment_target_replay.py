"""One-way physical replay of matched local source events on one target."""

from __future__ import annotations

import hashlib
import json
import math
import re

import numpy as np

from service.infrastructure.stimulation.population.pair_mapping import (
    match_fragment_inputs,
    schedule_matched_fragment_events,
    schedule_population_fragment_events,
)
from service.infrastructure.stimulation.swc_reference import (
    record_swc_with_stimulus_artifact,
    simulate_registered_swc_reference,
)


def replay_fragment_target(diagnostics, index, graph, target_id, directories, *,
                           simulation_parameters, recording, schedule_parameters,
                           max_source_distance_um, max_target_distance_um):
    """Compute a target contribution with and without its matched source events.

    The explicit synapse parameters and morphology registration are uncalibrated;
    the target does not feed back into the source or LIF network.
    """
    if (not isinstance(simulation_parameters, dict) or 'synaptic_events' in simulation_parameters
            or not isinstance(recording, dict)
            or set(recording) != {'electrode_um', 'reference_um', 'source_model'}
            or not isinstance(schedule_parameters, dict)
            or schedule_parameters.get('duration_ms') != simulation_parameters.get('duration_ms')):
        raise ValueError('Invalid matched target replay settings')
    mapping = match_fragment_inputs(diagnostics, index, graph, target_id, directories,
        max_source_distance_um=max_source_distance_um,
        max_target_distance_um=max_target_distance_um,
        duration_ms=int(simulation_parameters['duration_ms']))
    schedule = schedule_matched_fragment_events(mapping, **schedule_parameters)
    return _replay_target(mapping, schedule, target_id, directories, simulation_parameters,
                          recording, diagnostics.get('simulation_sha256'))


def replay_fragment_target_population(diagnostics, index, graph, target_id, directories, *,
                                      simulation_parameters, recording, schedule_parameters,
                                      max_source_distance_um, max_target_distance_um, max_events,
                                      timing_mode='tick'):
    """Replay multiple separately matched sources on a target without feedback."""
    if (not isinstance(diagnostics, list) or not diagnostics or len(diagnostics) > 256
            or not isinstance(schedule_parameters, list)
            or len(schedule_parameters) != len(diagnostics)
            or not isinstance(simulation_parameters, dict)
            or 'synaptic_events' in simulation_parameters
            or not isinstance(recording, dict)
            or set(recording) != {'electrode_um', 'reference_um', 'source_model'}
            or any(not isinstance(item, dict) for item in diagnostics)
            or any(not isinstance(settings, dict)
                   or settings.get('duration_ms') != simulation_parameters.get('duration_ms')
                   for settings in schedule_parameters)):
        raise ValueError('Invalid population target replay settings')
    duration = simulation_parameters.get('duration_ms')
    if (isinstance(duration, bool) or not isinstance(duration, int | float)
            or not math.isfinite(duration) or not duration > 0 or not float(duration).is_integer()):
        raise ValueError('Invalid population replay duration')
    source_digests = [item.get('simulation_sha256') for item in diagnostics]
    if (any(not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
            for digest in source_digests) or len(set(source_digests)) != 1):
        raise ValueError('Incompatible source field configurations')
    mappings = [match_fragment_inputs(item, index, graph, target_id, directories,
        max_source_distance_um=max_source_distance_um,
        max_target_distance_um=max_target_distance_um,
        duration_ms=int(simulation_parameters['duration_ms'])) for item in diagnostics]
    schedule = schedule_population_fragment_events(mappings, schedule_parameters,
                                                   max_events=max_events, timing_mode=timing_mode)
    mapping = {'target_id': schedule['target_id'],
               'target_morphology_sha256': schedule['target_morphology_sha256'],
               'graph_sha256': schedule['graph_sha256'], 'source_ids': schedule['source_ids'],
               'sources': mappings}
    return _replay_target(mapping, schedule, target_id, directories, simulation_parameters,
                          recording, source_digests[0])


def _replay_target(mapping, schedule, target_id, directories, simulation_parameters,
                   recording, expected_digest):
    baseline, baseline_proof = simulate_registered_swc_reference(
        target_id, directories, expected_morphology_sha256=mapping['target_morphology_sha256'],
        **simulation_parameters)
    config_hash = hashlib.sha256(json.dumps(baseline_proof['configuration'], sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf8')).hexdigest()
    if config_hash != expected_digest:
        raise ValueError('Target field configuration differs from source')
    active, active_proof = simulate_registered_swc_reference(
        target_id, directories, expected_morphology_sha256=mapping['target_morphology_sha256'],
        **simulation_parameters, synaptic_events=schedule['events'])
    if not np.array_equal(baseline['time_ms'], active['time_ms']):
        raise ValueError('Target replay time grids differ')
    baseline_voltage = np.asarray(baseline.get('voltage_mv'), dtype=float)
    active_voltage = np.asarray(active.get('voltage_mv'), dtype=float)
    if (baseline_voltage.ndim != 2 or not baseline_voltage.size
            or baseline_voltage.shape != active_voltage.shape
            or not np.isfinite(baseline_voltage).all() or not np.isfinite(active_voltage).all()):
        raise ValueError('Invalid target voltage traces')
    def channel(solution, proof):
        return record_swc_with_stimulus_artifact(solution, proof, recording['electrode_um'],
            recording['reference_um'], source_model=recording['source_model'])
    quiet_channel, active_channel = channel(baseline, baseline_proof), channel(active, active_proof)
    if not np.array_equal(quiet_channel['stimulus_artifact_uv'],
                          active_channel['stimulus_artifact_uv']):
        raise ValueError('Target replay stimulus artifacts differ')
    delta = active_channel['neural_uv'] - quiet_channel['neural_uv']
    if not np.isfinite(delta).all():
        raise ValueError('Non-finite target replay signal')
    probe = target_voltage_probe(baseline, active, schedule['events'],
                                 simulation_parameters['nseg_per_edge'])
    return {'mapping': mapping, 'schedule': schedule, 'time_ms': baseline['time_ms'],
            'baseline_neural_uv': quiet_channel['neural_uv'],
            'active_neural_uv': active_channel['neural_uv'], 'delta_neural_uv': delta,
            'stimulus_artifact_uv': active_channel['stimulus_artifact_uv'],
            'recording': recording,
            'voltage_range_mv': {'baseline_max': float(np.max(baseline_voltage)),
                                 'active_max': float(np.max(active_voltage)),
                                 'max_abs_difference': float(np.max(np.abs(
                                     active_voltage - baseline_voltage)))},
            'voltage_probe': probe,
            'baseline_provenance': baseline_proof, 'active_provenance': active_proof,
            'interpretation': 'one-way uncalibrated candidate-synapse replay; '
                              'not full-network physical recording or feedback'}


def target_voltage_probe(baseline, active, events, nseg_per_edge):
    """Record one explicit stimulated compartment; absence of events has no probe."""
    if not isinstance(events, list) or type(nseg_per_edge) is not int or nseg_per_edge <= 0:
        raise ValueError('Invalid target probe selection')
    if not events:
        return None
    event = events[0]
    if (not isinstance(event, dict) or type(event.get('child_node_id')) is not int
            or isinstance(event.get('position'), bool)
            or not isinstance(event.get('position'), int | float)
            or not 0 <= event['position'] <= 1):
        raise ValueError('Invalid target probe event')
    baseline_ids = np.asarray(baseline.get('edge_node_ids'))
    active_ids = np.asarray(active.get('edge_node_ids'))
    baseline_voltage = np.asarray(baseline.get('voltage_mv'), dtype=float)
    active_voltage = np.asarray(active.get('voltage_mv'), dtype=float)
    time = np.asarray(active.get('time_ms'), dtype=float)
    if (baseline_ids.ndim != 1 or not np.array_equal(baseline_ids, active_ids)
            or baseline_voltage.ndim != 2 or baseline_voltage.shape != active_voltage.shape
            or baseline_voltage.shape != (len(baseline_ids), len(time))
            or not np.isfinite(time).all() or not np.isfinite(baseline_voltage).all()
            or not np.isfinite(active_voltage).all()):
        raise ValueError('Incompatible target probe solutions')
    indices = np.flatnonzero(active_ids == event['child_node_id'])
    if len(indices) != nseg_per_edge or np.any(np.diff(indices) != 1):
        raise ValueError('Target probe compartment not found')
    segment = min(int(event['position'] * nseg_per_edge), nseg_per_edge - 1)
    index = int(indices[segment])
    return {'child_node_id': event['child_node_id'], 'segment_index': segment,
            'segments_per_edge': nseg_per_edge, 'segment_center': (segment + .5) / nseg_per_edge,
            'time_ms': time.copy(), 'baseline_mv': baseline_voltage[index].copy(),
            'active_mv': active_voltage[index].copy(),
            'interpretation': 'first matched event compartment; uncalibrated model voltage'}


def combine_fragment_target_recording(source, replay, *, source_ids):
    """Superpose disjoint source and replay currents, adding the common STIM artifact once."""
    if (not isinstance(source, dict) or not isinstance(replay, dict)
            or not isinstance(source_ids, list) or not source_ids
            or any(type(body) is not int or body <= 0 for body in source_ids)
            or len(set(source_ids)) != len(source_ids)):
        raise ValueError('Invalid recording populations')
    mapping, settings = replay.get('mapping'), replay.get('recording')
    replay_sources = (mapping.get('source_ids') if isinstance(mapping, dict)
                      and 'source_ids' in mapping else [mapping.get('source_id')]
                      if isinstance(mapping, dict) else None)
    if (not isinstance(mapping, dict) or not isinstance(replay_sources, list)
            or not replay_sources or any(type(body) is not int or body not in source_ids
                                         for body in replay_sources)
            or len(set(replay_sources)) != len(replay_sources)
            or type(mapping.get('target_id')) is not int or mapping['target_id'] <= 0
            or mapping['target_id'] in source_ids
            or not isinstance(settings, dict) or source.get('cells') != len(source_ids)
            or any(source.get(key) != settings.get(key)
                   for key in ('electrode_um', 'reference_um', 'source_model'))):
        raise ValueError('Source and target recordings are incompatible')
    time = np.asarray(source.get('time_ms'), dtype=float)
    neural = np.asarray(source.get('neural_uv'), dtype=float)
    artifact = np.asarray(source.get('stimulus_artifact_uv'), dtype=float)
    target = np.asarray(replay.get('active_neural_uv'), dtype=float)
    target_time = np.asarray(replay.get('time_ms'), dtype=float)
    target_artifact = np.asarray(replay.get('stimulus_artifact_uv'), dtype=float)
    source_total = np.asarray(source.get('total_uv'), dtype=float)
    if (time.ndim != 1 or len(time) < 2 or neural.shape != time.shape
            or artifact.shape != time.shape
            or target.shape != time.shape or source_total.shape != time.shape
            or not np.array_equal(time, target_time)
            or not np.array_equal(artifact, target_artifact)
            or not np.allclose(source_total, neural + artifact, rtol=1e-12, atol=1e-12)
            or any(not np.isfinite(values).all() for values in (time, neural, artifact, target))):
        raise ValueError('Source and target time grids or stimulus artifacts differ')
    combined = neural + target
    total = combined + artifact
    if not np.isfinite(total).all():
        raise ValueError('Non-finite combined recording')
    return {'time_ms': time.copy(), 'source_neural_uv': neural.copy(),
            'target_neural_uv': target.copy(), 'neural_uv': combined,
            'stimulus_artifact_uv': artifact.copy(), 'total_uv': total,
            'source_cells': len(source_ids), 'target_cells': 1,
            'interpretation': 'selected sources plus one independently replayed target; '
                              'one stimulus artifact; no target feedback'}
