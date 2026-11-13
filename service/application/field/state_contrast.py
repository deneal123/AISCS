"""Recalculate a field-run LIF contrast from its verified saved artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from service.infrastructure.connectome.forced_network import contrast_forced_network
from service.infrastructure.stimulation.field.graph_export import load_verified_field_graph_replay
from service.infrastructure.stimulation.synaptic_replay import _read_verified_spike_arrays
from service.infrastructure.stimulation.verified_spike_index import VerifiedSpikeIndex


def contrast_verified_field_run(directory: Path, graph, *, sample_cell_ids,
                                expected_manifest_sha256):
    """Verify the run, reproduce its graph events, then compare to a seeded control.

    Returned differences are relative LIF model states, not biological voltages.
    The caller supplies a trusted manifest digest from the owning saved run.
    """
    manifest_bytes = (directory / 'manifest.json').read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256:
        raise ValueError('Field manifest does not match trusted digest')
    saved = load_verified_field_graph_replay(directory, graph)
    if (directory / 'manifest.json').read_bytes() != manifest_bytes:
        raise ValueError('Field manifest changed during verification')
    metadata, binary = saved['metadata'], saved['graph_binary']
    description = metadata['graph_description']
    configuration = metadata['configuration']
    seed = configuration['seed']
    sources = [item['selection']['body_id'] for item in metadata['source_cells']]
    graph_sha = metadata['graph_sha256']
    source = VerifiedSpikeIndex(binary, description, graph_sha, graph.ids,
                                graph.provenance['manifest_sha256'])
    schedules = {int(body): [int(t) for t in ticks]
                 for body, ticks in source.select(sources).items()}
    result = contrast_forced_network(graph, seed=seed, duration_ms=description['duration_ms'],
                                     forced_cell_ids=sources, events=schedules,
                                     sample_cell_ids=sample_cell_ids)
    indices, times = _read_verified_spike_arrays(binary, description, graph_sha, graph.ids,
                                                  graph.provenance['manifest_sha256'])
    if (not np.array_equal(result['active_spike_neurons'], indices)
            or not np.array_equal(result['active_spike_times_ms'], times)):
        raise ValueError('Recomputed graph events differ from saved field run')
    return {
        **result,
        'provenance': {
            'field_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'graph_sha256': graph_sha,
            'graph_manifest_sha256': graph.provenance['manifest_sha256'],
            'seed': seed,
            'forced_cell_ids': sources,
            'interpretation': 'relative LIF states compared with the same seeded no-input control',
        },
    }
