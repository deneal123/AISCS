"""Replay explicit target inputs from a verified fragment-population result.

This is one-way, uncalibrated replay. It neither modifies the source result nor
creates feedback from the target to the network.
"""

from __future__ import annotations

from pathlib import Path

from service.application.replay.fragment_target_replay import (
    combine_fragment_target_recording,
    replay_fragment_target_population,
)
from service.domain.contracts.population.fragment import FragmentPopulationConfig
from service.infrastructure.stimulation.population.archive import (
    load_verified_fragment_population,
)


def replay_verified_population_target(directory: Path, graph, index, directories, *, target_id,
                                      source_ids, schedule_parameters, max_target_distance_um,
                                      max_events, timing_mode='tick'):
    """Check a saved result, replay selected sources and combine disjoint recordings."""
    if (type(target_id) is not int or target_id <= 0
            or not isinstance(source_ids, list) or not source_ids or len(source_ids) > 256
            or any(type(body) is not int or body <= 0 for body in source_ids)
            or len(set(source_ids)) != len(source_ids) or target_id in source_ids
            or not isinstance(schedule_parameters, list)
            or len(schedule_parameters) != len(source_ids)):
        raise ValueError('Invalid source or target selection')
    verified = load_verified_fragment_population(directory, graph)
    metadata, arrays = verified['metadata'], verified['arrays']
    config = FragmentPopulationConfig.model_validate(metadata['configuration'])
    if target_id in config.source_ids or any(body not in config.source_ids for body in source_ids):
        raise ValueError('Selected sources or target conflict with the verified population')
    diagnostics = metadata['diagnostics']
    if ([item.get('body_id') for item in diagnostics] != [str(body) for body in config.source_ids]):
        raise ValueError('Source diagnostics do not match the verified population')
    indexed = dict(zip(config.source_ids, diagnostics, strict=True))
    execution = config.execution_parameters()
    recording_settings = {key: execution[key]
                          for key in ('electrode_um', 'reference_um', 'source_model')}
    replay = replay_fragment_target_population(
        [indexed[body] for body in source_ids], index, graph, target_id, directories,
        simulation_parameters=execution['simulation_parameters'], recording=recording_settings,
        schedule_parameters=schedule_parameters, max_source_distance_um=config.max_distance_um,
        max_target_distance_um=max_target_distance_um, max_events=max_events,
        timing_mode=timing_mode,
    )
    source_recording = {**metadata['recording'], **{key: arrays[key] for key in (
        'time_ms', 'neural_uv', 'stimulus_artifact_uv', 'total_uv')}}
    combined = combine_fragment_target_recording(source_recording, replay,
                                                 source_ids=config.source_ids)
    return {'replay': replay, 'recording': combined,
            'source_configuration_sha256': config.digest(),
            'source_manifest': verified['manifest'],
            'source_population_ids': config.source_ids.copy(),
            'selected_source_ids': source_ids.copy(),
            'schedule_parameters': [dict(item) for item in schedule_parameters],
            'max_target_distance_um': max_target_distance_um, 'max_events': max_events,
            'interpretation': 'verified source archive and one-way target replay; '
                              'not validated tissue, full-network recording or feedback'}
