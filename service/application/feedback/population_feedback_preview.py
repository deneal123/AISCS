"""Bounded timeline for a verified coupled result; no interpolated physiology."""

from __future__ import annotations

from service.infrastructure.stimulation.fragment_population_preview import (
    fragment_population_preview,
)


def population_feedback_preview(result, graph, source_config):
    recording, network = result['recording'], result['network']
    ids = result['physical_source_output']['source_ids']
    duration = int(source_config.simulation.duration_ms)
    arrays = {name: recording[name] for name in
              ('time_ms', 'neural_uv', 'total_uv', 'stimulus_fraction')}
    arrays['spike_times_ms'] = network['spike_times_ms']
    traces = fragment_population_preview(arrays, source_count=len(ids), duration_ms=duration,
        edge_event_count=len(result['physical_source_output']['edge_events']))
    preview = {'kind': 'experimental-coupled-population', 'status': result['status'],
            'source_cells': len(ids), 'source_ids': ids.copy(), 'graph_cells': graph.size,
            'graph_sha256': source_config.graph_manifest_sha256,
            'source_configuration_sha256': source_config.digest(),
            'duration_ms': duration, 'network_spikes': len(network['spike_neurons']),
            'unresolved_candidates': len(result['schedule']['unresolved']),
            'iterations': len(result['iterations']),
            'interpretation': 'physical recording is limited to source cells; '
                              'the remaining network is uncalibrated LIF',
            'timeline': {key: traces[key] for key in ('samples', 'shown_samples',
                'stimulus_boundaries_preserved', 'time_ms', 'neural_uv', 'total_uv',
                'stimulus_fraction', 'network_spikes_by_ms', 'edge_event_count', 'units')}}
    if source_config.allow_partial_geometry is True:
        preview['source_unresolved_graph_pairs'] = result['physical_source_output'][
            'source_unresolved_graph_pairs']
    receipt = result.get('discretization_receipt')
    if receipt is not None:
        rows = [row for target in receipt['targets'].values() for row in target['evidence']]
        preview['geometry_discretization'] = {
            'checked_events': receipt['observation_audit']['verified_events'],
            'relocated_endpoints': sum(row['requires_endpoint_relocation'] for row in rows),
            'max_shift_um': max((row['shift_um'] for row in rows
                                 if row['requires_endpoint_relocation']), default=0.),
            'max_observation_distance_um': max(
                (row['observation_distance_um'] for row in rows), default=0.),
        }
    return preview
