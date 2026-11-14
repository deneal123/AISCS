"""Validate full detailed-population feedback outputs before publication."""

import hashlib
import json
import math
import re


class InvalidFullFeedbackManifest(ValueError):
    pass


def validate_full_feedback_manifest(manifest, *, configuration_sha256, graph_sha256, graph_cells,
                                    request_sha256=None, request_configuration=None):
    """Validate identities and file declarations; callers separately verify file bytes."""
    names = {'initial-active.jsonl', 'control.jsonl', 'activity.jsonl', 'signals.npz',
             'preview.json', 'coupled-source-events.bin'}
    if (not isinstance(manifest, dict)
            or manifest.get('kind') != 'experimental-full-population-feedback'
            or manifest.get('status') != 'converged'
            or any(not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value)
                   for value in (configuration_sha256, graph_sha256))
            or manifest.get('configuration_sha256') != configuration_sha256
            or manifest.get('graph_sha256') != graph_sha256
            or type(graph_cells) is not int or not 1 <= graph_cells <= 5_000_000
            or type(manifest.get('cells')) is not int or manifest['cells'] != graph_cells
            or type(manifest.get('iterations')) is not int or manifest['iterations'] < 1
            or type(manifest.get('control_iterations')) is not int
            or manifest['control_iterations'] < 1
            or not isinstance(manifest.get('control_feedback_schedule_sha256'), str)
            or not re.fullmatch('[a-f0-9]{64}', manifest['control_feedback_schedule_sha256'])
            or not isinstance(manifest.get('configuration'), dict)):
        raise InvalidFullFeedbackManifest('full_feedback_identity')
    try:
        config = json.dumps(manifest['configuration'], sort_keys=True,
                            separators=(',', ':'), allow_nan=False).encode('utf8')
    except (TypeError, ValueError) as exc:
        raise InvalidFullFeedbackManifest('full_feedback_configuration') from exc
    if (hashlib.sha256(config).hexdigest() != configuration_sha256
            or manifest['configuration'].get('graph_sha256') != graph_sha256
            or (request_sha256 is not None and (
                not isinstance(request_sha256, str)
                or not re.fullmatch('[a-f0-9]{64}', request_sha256)
                or manifest['configuration'].get('request_sha256') != request_sha256))
            or type(manifest['configuration'].get('max_iterations')) is not int
            or manifest['iterations'] > manifest['configuration']['max_iterations']
            or manifest['control_iterations'] > manifest['configuration']['max_iterations']):
        raise InvalidFullFeedbackManifest('full_feedback_configuration')
    if request_configuration is not None:
        if not isinstance(request_configuration, dict):
            raise InvalidFullFeedbackManifest('full_feedback_request')
        numerical = manifest['configuration']
        shared = ('simulation', 'threshold_mv', 'max_source_distance_um',
                  'max_target_distance_um', 'max_iterations', 'max_events')
        if (any(key not in request_configuration or numerical.get(key) != request_configuration[key]
                for key in shared)
                or numerical.get('synapse_parameters') != {
                    '1': request_configuration.get('excitatory'),
                    '-1': request_configuration.get('inhibitory')}
                or (not request_configuration.get('allow_known_geometry_repair', False)
                    and numerical.get('geometry_repair') is not None)):
            raise InvalidFullFeedbackManifest('full_feedback_request')
    entries, digests = manifest.get('files'), manifest.get('file_hashes')
    if (not isinstance(entries, list) or len(entries) != len(names)
            or not isinstance(digests, dict) or set(digests) != names):
        raise InvalidFullFeedbackManifest('full_feedback_files')
    found = set()
    for item in entries:
        if (not isinstance(item, dict) or set(item) != {'name', 'bytes', 'sha256'}
                or item['name'] not in names or item['name'] in found
                or type(item['bytes']) is not int or item['bytes'] < 1
                or (item['name'] == 'preview.json' and item['bytes'] > 1024 * 1024)
                or not isinstance(item['sha256'], str)
                or not re.fullmatch('[a-f0-9]{64}', item['sha256'])
                or digests.get(item['name']) != item['sha256']):
            raise InvalidFullFeedbackManifest('full_feedback_files')
        found.add(item['name'])
    if found != names:
        raise InvalidFullFeedbackManifest('full_feedback_files')


def validate_full_feedback_preview(preview, *, manifest):
    configuration = manifest.get('configuration') if isinstance(manifest, dict) else None
    simulation = configuration.get('simulation') if isinstance(configuration, dict) else None
    if (not isinstance(preview, dict) or not isinstance(manifest, dict)
            or not isinstance(simulation, dict)
            or preview.get('kind') != 'experimental-full-population-feedback'
            or preview.get('status') != 'converged'
            or type(preview.get('graph_cells')) is not int
            or preview['graph_cells'] != manifest.get('cells')
            or type(preview.get('source_cells')) is not int
            or preview['source_cells'] != preview['graph_cells']
            or type(preview.get('duration_ms')) is not int or preview['duration_ms'] < 1
            or preview['duration_ms'] != simulation.get('duration_ms')
            or type(preview.get('iterations')) is not int
            or preview['iterations'] != manifest.get('iterations')
            or type(preview.get('control_iterations')) is not int
            or preview['control_iterations'] != manifest.get('control_iterations')
            or type(preview.get('candidate_cell_time_markers')) is not int
            or not 0 <= preview['candidate_cell_time_markers'] <= (
                preview['graph_cells'] * preview['duration_ms'])):
        raise InvalidFullFeedbackManifest('full_feedback_preview')
    timeline = preview.get('timeline')
    if not isinstance(timeline, dict):
        raise InvalidFullFeedbackManifest('full_feedback_timeline')
    rows = [timeline.get(name) for name in ('time_ms', 'neural_uv', 'control_uv',
                                           'stimulus_fraction')]
    shown, samples = timeline.get('shown_samples'), timeline.get('samples')
    dt = simulation.get('dt_ms')
    if (type(shown) is not int or type(samples) is not int or not 2 <= shown <= min(samples, 3200)
            or any(not isinstance(row, list) or len(row) != shown for row in rows)
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   for row in rows for value in row)
            or rows[0][0] != 0
            or not math.isclose(rows[0][-1], preview['duration_ms'], abs_tol=1e-9)
            or any(left >= right for left, right in zip(rows[0], rows[0][1:], strict=False))
            or type(dt) not in (int, float) or not math.isfinite(dt) or dt <= 0
            or samples != round(preview['duration_ms'] / dt) + 1
            or any(not math.isclose(round(value / dt) * dt, value, abs_tol=1e-9)
                   for value in rows[0])
            or timeline.get('units') != {'time_ms': 'ms', 'neural_uv': 'µV', 'control_uv': 'µV'}):
        raise InvalidFullFeedbackManifest('full_feedback_timeline')
