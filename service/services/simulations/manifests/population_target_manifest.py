"""Validate one-way target replay artifacts before platform publication."""

from __future__ import annotations

import math
import re


class InvalidPopulationTargetManifest(ValueError):
    pass


def validate_population_target_manifest(manifest, *, configuration_sha256):
    expected = {'target-model.json', 'target-signals.npz', 'target-preview.json'}
    if (not isinstance(manifest, dict)
            or manifest.get('kind') != 'experimental-one-way-target-replay'
            or not isinstance(configuration_sha256, str)
            or not re.fullmatch(r'[a-f0-9]{64}', configuration_sha256)
            or manifest.get('configuration_sha256') != configuration_sha256
            or not isinstance(manifest.get('files'), list) or len(manifest['files']) != 3):
        raise InvalidPopulationTargetManifest('target_identity')
    names = set()
    for item in manifest['files']:
        if (not isinstance(item, dict) or set(item) != {'name', 'bytes', 'sha256'}
                or item['name'] not in expected or item['name'] in names
                or type(item['bytes']) is not int or not 1 <= item['bytes'] <= 256 * 1024 * 1024
                or (item['name'] == 'target-preview.json' and item['bytes'] > 1024 * 1024)
                or not isinstance(item['sha256'], str)
                or not re.fullmatch(r'[a-f0-9]{64}', item['sha256'])):
            raise InvalidPopulationTargetManifest('target_files')
        names.add(item['name'])
    if names != expected:
        raise InvalidPopulationTargetManifest('target_files')


def validate_population_target_preview(preview, configuration, source_configuration):
    try:
        duration, dt = configuration['duration_ms'], source_configuration['simulation']['dt_ms']
        names = ('time_ms', 'source_neural_uv', 'target_neural_uv', 'target_delta_uv',
                 'neural_uv', 'stimulus_artifact_uv', 'total_uv')
        probe = preview.get('voltage_probe')
        if probe is not None:
            names += ('probe_baseline_mv', 'probe_active_mv')
        samples, shown = preview['samples'], preview['shown_samples']
        traces = [preview[name] for name in names]
        if (type(duration) is not int or not 1 <= duration <= 1000
                or type(dt) not in (int, float) or not math.isfinite(dt) or dt <= 0
                or type(samples) is not int or samples != round(duration / dt) + 1
                or type(shown) is not int or not 2 <= shown <= min(samples, 4500 if probe else 3500)
                or any(not isinstance(trace, list) or len(trace) != shown for trace in traces)
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for trace in traces for value in trace)
                or not math.isclose(traces[0][0], 0, abs_tol=1e-8)
                or not math.isclose(traces[0][-1], duration, rel_tol=0, abs_tol=1e-8)
                or any(a >= b for a, b in zip(traces[0], traces[0][1:], strict=False))
                or any(not 0 <= round(time / dt) < samples
                       or not math.isclose(time, round(time / dt) * dt, rel_tol=0,
                                           abs_tol=min(1e-8, dt * 1e-3))
                       for time in traces[0])
                or any(not math.isclose(n, s + t, rel_tol=1e-10, abs_tol=1e-10)
                       for s, t, n in zip(traces[1], traces[2], traces[4], strict=True))
                or any(not math.isclose(total, n + artifact, rel_tol=1e-10, abs_tol=1e-10)
                       for n, artifact, total in zip(traces[4], traces[5], traces[6], strict=True))
                or type(preview['source_cells']) is not int
                or preview['source_cells'] != len(source_configuration['source_ids'])
                or preview['target_cells'] != 1 or type(preview['target_cells']) is not int
                or preview['target_id'] != configuration['target_id']
                or preview['selected_source_ids'] != configuration['source_ids']
                or type(preview['events']) is not int or preview['events'] < 0
                or preview['events'] > configuration['max_events']
                or preview['units'] != {'time_ms': 'ms', 'signal': 'µV'}
                or preview['limitations'] != [
                    'Односторонний повтор без обратной связи с сетью.',
                    'Физическая запись ограничена указанными клетками.',
                    'Параметры синапсов и тканей не откалиброваны.']):
            raise InvalidPopulationTargetManifest('target_preview')
        if probe is not None and (
                not isinstance(probe, dict)
                or set(probe) != {'child_node_id', 'segment_index', 'segments_per_edge',
                                  'segment_center', 'interpretation'}
                or type(probe['child_node_id']) is not int or probe['child_node_id'] <= 0
                or type(probe['segment_index']) is not int
                or type(probe['segments_per_edge']) is not int or probe['segments_per_edge'] <= 0
                or not 0 <= probe['segment_index'] < probe['segments_per_edge']
                or probe['segment_center']
                   != (probe['segment_index'] + .5) / probe['segments_per_edge']
                or probe['interpretation']
                   != 'first matched event compartment; uncalibrated model voltage'
                or preview['events'] < 1):
            raise InvalidPopulationTargetManifest('target_probe')
        if probe is None and ('probe_baseline_mv' in preview or 'probe_active_mv' in preview):
            raise InvalidPopulationTargetManifest('target_probe')
        morphology = preview.get('probe_morphology_sha256')
        if morphology is not None and (probe is None or not isinstance(morphology, str)
                                       or not re.fullmatch(r'[a-f0-9]{64}', morphology)):
            raise InvalidPopulationTargetManifest('target_probe_morphology')
        if preview.get('timing_mode') != configuration.get('timing_mode'):
            raise InvalidPopulationTargetManifest('target_timing_mode')
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise InvalidPopulationTargetManifest('target_preview') from exc
