"""Combine independently verified source batches before one network calculation.

This does not provide feedback to physical sources or a physical recording of
the remaining graph. Batches must describe the same electrodes and stimulus.
"""

from __future__ import annotations

import numpy as np

from service.domain.contracts.fragment_population_contract import FragmentPopulationConfig
from service.infrastructure.connectome.edge_forced_network import run_edge_forced_network
from service.infrastructure.connectome.source_feedback import suppressed_source_inputs
from service.infrastructure.stimulation.fragment_population_archive import (
    load_verified_fragment_population,
)


def merge_fragment_batches(graph, directories):
    """Verify batches, sum source currents once, then propagate one shared graph.

    Source batches are deliberately required to be disjoint. The saved graph
    outputs from individual batches are not combined: nonlinear LIF dynamics
    must be recalculated from the joint input.
    """
    if not isinstance(directories, list | tuple) or not directories:
        raise ValueError('At least one batch is required')
    reference = None
    seen = set()
    events = []
    sources = []
    signal = None
    fingerprints = []
    for directory in directories:
        batch = load_verified_fragment_population(directory, graph)
        metadata, arrays = batch['metadata'], batch['arrays']
        config = FragmentPopulationConfig.model_validate(metadata['configuration'])
        common = config.model_dump(mode='json', exclude={'source_ids'})
        if reference is None:
            reference = (common, arrays['time_ms'].copy(), arrays['stimulus_fraction'].copy(),
                         arrays['stimulus_artifact_uv'].copy())
            signal = np.zeros_like(arrays['neural_uv'], dtype=np.float64)
        elif (common != reference[0] or not np.array_equal(arrays['time_ms'], reference[1])
              or not np.array_equal(arrays['stimulus_fraction'], reference[2])
              or not np.array_equal(arrays['stimulus_artifact_uv'], reference[3])):
            raise ValueError('Source batches have incompatible stimulus or recording settings')
        if seen.intersection(config.source_ids):
            raise ValueError('Source batches overlap')
        seen.update(config.source_ids)
        sources.extend(config.source_ids)
        signal += arrays['neural_uv']
        if not np.isfinite(signal).all():
            raise ValueError('Non-finite combined signal')
        for schedule in metadata['schedules']:
            events.extend(schedule['edge_events'])
            if len(events) > 1_000_000:
                raise ValueError('Combined network schedule exceeds event limit')
        fingerprints.append(batch['manifest']['configuration_sha256'])
    if len(sources) >= graph.size:
        raise ValueError('No active graph cells remain; sources have no network feedback')
    source_inputs = [event for event in events if event['target_id'] in seen]
    network = run_edge_forced_network(
        graph, seed=reference[0]['seed'],
        duration_ms=int(reference[0]['simulation']['duration_ms']),
        forced_cell_ids=sources, edge_events=events, capture_sparse_delta=True,
    )
    feedback = suppressed_source_inputs(graph, sources, events, network,
                                        duration_ms=int(reference[0]['simulation']['duration_ms']))
    total = signal + reference[3]
    if not np.isfinite(total).all():
        raise ValueError('Non-finite combined recording')
    return {'source_ids': sources, 'source_configuration_sha256': fingerprints,
            'source_targeted_edge_events': len(source_inputs),
            'source_targeted_synaptic_events': sum(event['count'] for event in source_inputs),
            'suppressed_inputs': feedback,
            'time_ms': reference[1], 'stimulus_fraction': reference[2], 'neural_uv': signal,
            'stimulus_artifact_uv': reference[3], 'total_uv': total, 'network': network,
            'interpretation': 'independent source batches; one combined LIF run; '
                              'no feedback and no full-network physical recording'}
