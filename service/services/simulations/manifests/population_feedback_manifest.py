"""Validate bounded experimental coupled-population results before publication."""

from __future__ import annotations

import hashlib
import json
import math
import re


class InvalidPopulationFeedbackManifest(ValueError):
    pass


def validate_population_feedback_manifest(manifest, *, configuration_sha256, configuration):
    required_names = {'coupled-population.zip', 'coupled-preview.json', 'coupled-delta.bin',
             'coupled-events.bin'}
    names = required_names | {'coupled-source-events.bin'}
    if (not isinstance(manifest, dict)
            or not isinstance(configuration, dict)
            or manifest.get('kind') != 'experimental-coupled-population'
            or not isinstance(configuration_sha256, str)
            or not re.fullmatch(r'[a-f0-9]{64}', configuration_sha256)
            or manifest.get('configuration_sha256') != configuration_sha256
            or manifest.get('source_package_sha256') != configuration.get('source_package_sha256')
            or manifest.get('source_manifest_sha256') != configuration.get('source_manifest_sha256')
            or manifest.get('graph_sha256') != configuration.get('graph_manifest_sha256')
            or any(not isinstance(configuration.get(key), str)
                   or not re.fullmatch(r'[a-f0-9]{64}', configuration[key])
                   for key in ('source_package_sha256', 'source_manifest_sha256'))
            or not isinstance(manifest.get('files'), list) or len(manifest['files']) not in (4, 5)):
        raise InvalidPopulationFeedbackManifest('feedback_identity')
    found = set()
    for item in manifest['files']:
        if (not isinstance(item, dict) or set(item) != {'name', 'bytes', 'sha256'}
                or item['name'] not in names or item['name'] in found
                or type(item['bytes']) is not int or not 1 <= item['bytes'] <= 256 * 1024 * 1024
                or (item['name'] == 'coupled-preview.json' and item['bytes'] > 1024 * 1024)
                or not isinstance(item['sha256'], str)
                or not re.fullmatch(r'[a-f0-9]{64}', item['sha256'])):
            raise InvalidPopulationFeedbackManifest('feedback_files')
        found.add(item['name'])
    if not required_names <= found:
        raise InvalidPopulationFeedbackManifest('feedback_files')


def validate_population_feedback_preview(preview, configuration, source_configuration):
    if (not isinstance(preview, dict) or not isinstance(source_configuration, dict)
            or preview.get('kind') != 'experimental-coupled-population'
            or preview.get('status') not in ('converged', 'converged_partial')
            or type(preview.get('source_cells')) is not int
            or not isinstance(source_configuration.get('source_ids'), list)
            or preview['source_cells'] != len(source_configuration['source_ids'])
            or preview.get('source_ids') != source_configuration['source_ids']
            or preview.get('graph_sha256') != configuration.get('graph_manifest_sha256')
            or preview.get('source_configuration_sha256') != hashlib.sha256(json.dumps(
                source_configuration, sort_keys=True, separators=(',', ':'),
                allow_nan=False).encode('utf8')).hexdigest()
            or type(preview.get('graph_cells')) is not int
            or not preview['source_cells'] <= preview['graph_cells'] <= 5_000_000
            or type(preview.get('network_spikes')) is not int or preview['network_spikes'] < 0
            or type(preview.get('unresolved_candidates')) is not int
            or preview['unresolved_candidates'] < 0
            or (source_configuration.get('allow_partial_geometry') is True
                and (type(preview.get('source_unresolved_graph_pairs')) is not int
                     or preview['source_unresolved_graph_pairs'] < 0))
            or (source_configuration.get('allow_partial_geometry') is not True
                and 'source_unresolved_graph_pairs' in preview)
            or (preview['status'] == 'converged_partial')
                != (preview['unresolved_candidates'] > 0
                    or preview.get('source_unresolved_graph_pairs', 0) > 0)
            or ((preview['unresolved_candidates'] > 0
                 or preview.get('source_unresolved_graph_pairs', 0) > 0)
                and configuration.get('allow_partial_geometry') is not True)
            or type(preview.get('iterations')) is not int
            or type(configuration.get('max_iterations')) is not int
            or not 1 <= preview['iterations'] <= configuration['max_iterations']
            or preview.get('interpretation') != 'physical recording is limited to source cells; '
                                                 'the remaining network is uncalibrated LIF'):
        raise InvalidPopulationFeedbackManifest('feedback_preview')
    refinement = configuration.get('discretization')
    geometry = preview.get('geometry_discretization')
    if refinement is None:
        if geometry is not None:
            raise InvalidPopulationFeedbackManifest('feedback_discretization')
    elif (not isinstance(refinement, dict) or not isinstance(geometry, dict)
          or set(geometry) != {'checked_events', 'relocated_endpoints', 'max_shift_um',
                               'max_observation_distance_um'}
          or any(type(geometry.get(key)) is not int or geometry[key] < 0
                 for key in ('checked_events', 'relocated_endpoints'))
          or geometry['relocated_endpoints'] > geometry['checked_events']
          or any(type(geometry.get(key)) not in (int, float)
                 or not math.isfinite(geometry[key]) or geometry[key] < 0
                 or type(refinement.get(key)) not in (int, float)
                 or not math.isfinite(refinement[key]) or geometry[key] > refinement[key] + 1e-9
                 for key in ('max_shift_um', 'max_observation_distance_um'))):
        raise InvalidPopulationFeedbackManifest('feedback_discretization')
    try:
        simulation = source_configuration['simulation']
        duration, dt = simulation['duration_ms'], simulation['dt_ms']
        timeline = preview['timeline']
        samples, shown = timeline['samples'], timeline['shown_samples']
        times, neural, total, stimulus = (timeline[name] for name in
            ('time_ms', 'neural_uv', 'total_uv', 'stimulus_fraction'))
        spikes = timeline['network_spikes_by_ms']
        if (type(duration) not in (int, float) or not math.isfinite(duration)
                or not 1 <= duration <= 1000 or duration != int(duration)
                or type(dt) not in (int, float) or not math.isfinite(dt) or dt <= 0
                or preview.get('duration_ms') != duration
                or type(samples) is not int or samples != round(duration / dt) + 1
                or type(shown) is not int or not 2 <= shown <= min(samples, 4096)
                or type(timeline['stimulus_boundaries_preserved']) is not bool
                or any(not isinstance(x, list) or len(x) != shown
                       for x in (times, neural, total, stimulus))
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for row in (times, neural, total, stimulus) for value in row)
                or not math.isclose(times[0], 0, abs_tol=1e-8)
                or not math.isclose(times[-1], duration, abs_tol=1e-8)
                or any(a >= b for a, b in zip(times, times[1:], strict=False))
                or any(not math.isclose(value, round(value / dt) * dt, abs_tol=1e-8)
                       for value in times)
                or not isinstance(spikes, list) or len(spikes) != int(duration) + 1
                or any(type(value) is not int or value < 0 for value in spikes)
                or sum(spikes) != preview['network_spikes']
                or type(timeline['edge_event_count']) is not int
                or timeline['edge_event_count'] < 0
                or timeline['units'] != {'time_ms': 'ms', 'neural_uv': 'µV', 'total_uv': 'µV'}):
            raise InvalidPopulationFeedbackManifest('feedback_timeline')
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
        raise InvalidPopulationFeedbackManifest('feedback_timeline') from exc
