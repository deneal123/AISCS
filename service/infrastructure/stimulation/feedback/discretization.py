"""Prepare verified feedback geometry for an explicitly bounded cable replay.

This module does not choose limits or enable approximations in the production
executor. Geometry alone cannot establish numerical or biological validity.
"""

from __future__ import annotations

from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.stimulation.feedback.endpoint_discretization import (
    prepare_discretized_events,
)
from service.infrastructure.stimulation.feedback.observation_audit import (
    audit_feedback_observations,
)


def prepare_feedback_discretization(schedule, index, directories, *, expected_source_md5,
                                    max_shift_um, max_observation_distance_um, max_nseg,
                                    _pair_cache=None):
    """Verify source geometry and prepare each target without mutating the schedule."""
    cache_options = {'_pair_cache': _pair_cache} if _pair_cache is not None else {}
    proof = audit_feedback_observations(schedule, index, directories,
                                        expected_source_md5=expected_source_md5, **cache_options)
    prepared = {}
    for body, events in schedule['events_by_target'].items():
        if not events:
            continue
        origins = schedule['provenance_by_target'][body]
        if any('source_position_8nm' not in row for row in origins):
            raise ValueError('Both source and target observations are required')
        source = read_skeleton(body, directories,
                               expected_sha256=schedule['target_morphology_sha256'][body])
        nodes = {}
        for line in source['swc'].splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            row = line.split()
            nodes[int(row[0])] = ([float(value) * .008 for value in row[2:5]], int(row[6]))
        edges = {child: [nodes[parent][0], point]
                 for child, (point, parent) in nodes.items() if parent != -1}
        observations = [[value * .008 for value in origin['target_position_8nm']]
                        for origin in origins]
        prepared[body] = prepare_discretized_events(
            events, edges, observations, max_shift_um=max_shift_um,
            max_observation_distance_um=max_observation_distance_um, max_nseg=max_nseg)
    return {'targets': prepared, 'observation_audit': proof,
            'interpretation': 'verified indexed positions and bounded approximation; '
                              'not a validated full-network physical calculation'}


def verify_feedback_discretization(schedule, receipt, index, directories, *, policy):
    """Rebuild a receipt from trusted inputs and externally chosen limits.

    A receipt or its checksum alone does not establish which synapses, source
    data, morphology, or policy the calculation actually used.
    """
    if (not isinstance(policy, dict) or set(policy) != {
            'expected_source_md5', 'max_shift_um', 'max_observation_distance_um', 'max_nseg'}
            or not isinstance(receipt, dict)):
        raise ValueError('Explicit verification policy and receipt required')
    rebuilt = prepare_feedback_discretization(schedule, index, directories, **policy)
    if receipt != rebuilt:
        raise ValueError('Feedback discretization receipt does not match verified inputs')
    return rebuilt
