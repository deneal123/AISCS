"""Validate independent detailed-cell results without implying network feedback."""

import math
import re


def validate_independent_manifest(manifest, *, configuration_sha256):
    if (not isinstance(manifest, dict) or manifest.get('format') != 'independent-gpu-recording-v1'
            or manifest.get('kind') != 'experimental-independent-population'
            or manifest.get('configuration_sha256') != configuration_sha256
            or not isinstance(configuration_sha256, str)
            or not re.fullmatch(r'[a-f0-9]{64}', configuration_sha256)
            or manifest.get('geometry_repair_policy') not in ('disabled', 'verified-842998')
            or not isinstance(manifest.get('interpretation'), str)
            or 'no network feedback' not in manifest['interpretation']):
        raise ValueError('independent_manifest_identity')
    for key in ('geometry_cache_manifest_sha256', 'source_index_sha256'):
        if (not isinstance(manifest.get(key), str)
                or not re.fullmatch(r'[a-f0-9]{64}', manifest[key])):
            raise ValueError('independent_manifest_identity')
    files = manifest.get('files')
    if not isinstance(files, list) or len(files) != 2:
        raise ValueError('independent_manifest_files')
    names = set()
    for item in files:
        if (not isinstance(item, dict) or item.get('name') not in {'recording.npz', 'preview.json'}
                or item['name'] in names or type(item.get('bytes')) is not int
                or not 1 <= item['bytes'] <= 256 * 1024 * 1024
                or (item['name'] == 'preview.json' and item['bytes'] > 1024 * 1024)
                or not isinstance(item.get('sha256'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', item['sha256'])):
            raise ValueError('independent_manifest_files')
        names.add(item['name'])


def validate_independent_preview(preview, configuration):
    if not isinstance(preview, dict) or not isinstance(configuration, dict):
        raise ValueError('independent_preview')
    time, signal = preview.get('time_ms'), preview.get('neural_uv')
    if (preview.get('kind') != 'experimental-independent-population'
            or type(preview.get('cells')) is not int or not 1 <= preview['cells'] <= 166700
            or type(preview.get('samples')) is not int or preview['samples'] < 2
            or type(preview.get('replacement_count')) is not int
            or not 0 <= preview['replacement_count'] <= preview['cells']
            or not isinstance(preview.get('interpretation'), str)
            or 'no network feedback' not in preview['interpretation']
            or preview.get('units') != {'time_ms': 'ms', 'neural_uv': 'µV'}
            or not isinstance(time, list) or not isinstance(signal, list)
            or len(time) != len(signal) or not 2 <= len(time) <= 1600
            or preview.get('shown_samples') != len(time) or len(time) > preview['samples']
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in time + signal)
            or time[0] != 0 or any(a >= b for a, b in zip(time, time[1:], strict=False))):
        raise ValueError('independent_preview')
    simulation = configuration.get('simulation')
    if (not isinstance(simulation, dict) or type(simulation.get('duration_ms')) not in (int, float)
            or not math.isclose(time[-1], simulation['duration_ms'], rel_tol=0, abs_tol=1e-9)):
        raise ValueError('independent_preview_time')
    if 'dt_ms' in simulation:
        dt = simulation['dt_ms']
        if (type(dt) not in (int, float) or not math.isfinite(dt) or dt <= 0
                or not math.isfinite(simulation['duration_ms'])
                or not math.isfinite(simulation['duration_ms'] / dt)
                or simulation['duration_ms'] / dt > 40000
                or not math.isclose(round(simulation['duration_ms'] / dt) * dt,
                                    simulation['duration_ms'], rel_tol=0, abs_tol=1e-9)
                or preview['samples'] != round(simulation['duration_ms'] / dt) + 1
                or any(not math.isclose(round(value / dt) * dt, value,
                                        rel_tol=0, abs_tol=1e-9) for value in time)):
            raise ValueError('independent_preview_grid')
