"""Integrity-checked artifacts for an explicitly limited target replay."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import zipfile
from pathlib import Path

import numpy as np

from service.infrastructure.connectome.forced_network import validate_crossing_intervals
from service.infrastructure.stimulation.fragment_pair_mapping import (
    schedule_population_fragment_events,
)

ARRAY_NAMES = ('time_ms', 'source_neural_uv', 'target_neural_uv', 'neural_uv',
               'stimulus_artifact_uv', 'total_uv', 'target_baseline_uv', 'target_delta_uv')
PROBE_ARRAY_NAMES = ('probe_baseline_mv', 'probe_active_mv')
MAX_BYTES = 256 * 1024 * 1024


def _json(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                       allow_nan=False) + '\n').encode('utf8')


def _validate(arrays):
    if set(arrays) not in (set(ARRAY_NAMES), set(ARRAY_NAMES + PROBE_ARRAY_NAMES)):
        raise ValueError('Invalid target replay arrays')
    time = arrays['time_ms']
    if (time.ndim != 1 or len(time) < 2 or not np.isfinite(time).all()
            or np.any(np.diff(time) <= 0)
            or any(values.shape != time.shape or not np.isfinite(values).all()
                   for values in arrays.values())
            or not np.allclose(arrays['neural_uv'], arrays['source_neural_uv']
                               + arrays['target_neural_uv'], rtol=1e-12, atol=1e-12)
            or not np.allclose(arrays['total_uv'], arrays['neural_uv']
                               + arrays['stimulus_artifact_uv'], rtol=1e-12, atol=1e-12)
            or not np.allclose(arrays['target_delta_uv'], arrays['target_neural_uv']
                               - arrays['target_baseline_uv'], rtol=1e-12, atol=1e-12)):
        raise ValueError('Inconsistent target replay recording')


def _validate_metadata(metadata):
    if not isinstance(metadata, dict):
        raise ValueError('Invalid target replay metadata')
    all_ids, selected = metadata.get('source_population_ids'), metadata.get('selected_source_ids')
    source_manifest, mapping, schedule = (metadata.get('source_manifest'), metadata.get('mapping'),
                                           metadata.get('schedule'))
    if (not isinstance(all_ids, list) or not 1 <= len(all_ids) <= 256
            or any(type(body) is not int or not 0 < body < 2**63 for body in all_ids)
            or len(set(all_ids)) != len(all_ids)
            or not isinstance(selected, list) or not selected
            or any(type(body) is not int or body not in all_ids for body in selected)
            or len(set(selected)) != len(selected)
            or not isinstance(source_manifest, dict)
            or source_manifest.get('kind') != 'experimental-fragment-population'
            or not isinstance(metadata.get('source_configuration_sha256'), str)
            or not re.fullmatch(r'[a-f0-9]{64}', metadata['source_configuration_sha256'])
            or source_manifest.get('configuration_sha256')
               != metadata['source_configuration_sha256']
            or not isinstance(mapping, dict) or mapping.get('source_ids') != selected
            or type(mapping.get('target_id')) is not int or mapping['target_id'] in all_ids
            or not 0 < mapping['target_id'] < 2**63
            or not isinstance(mapping.get('graph_sha256'), str)
            or not re.fullmatch(r'[a-f0-9]{64}', mapping['graph_sha256'])
            or not isinstance(mapping.get('target_morphology_sha256'), str)
            or not re.fullmatch(r'[a-f0-9]{64}', mapping['target_morphology_sha256'])
            or mapping.get('graph_sha256') != source_manifest.get('graph_sha256')
            or not isinstance(schedule, dict) or schedule.get('source_ids') != selected
            or not isinstance(schedule.get('events'), list)
            or schedule.get('target_id') != mapping['target_id']
            or schedule.get('graph_sha256') != mapping.get('graph_sha256')
            or schedule.get('target_morphology_sha256') != mapping.get('target_morphology_sha256')
            or not isinstance(metadata.get('schedule_parameters'), list)
            or len(metadata['schedule_parameters']) != len(selected)
            or metadata.get('source_cells') != len(all_ids) or metadata.get('target_cells') != 1):
        raise ValueError('Inconsistent target replay metadata')
    mode = schedule.get('timing_mode')
    if mode not in (None, 'upper_bound', 'lower_bound'):
        raise ValueError('Invalid target timing mode')
    if mode in ('upper_bound', 'lower_bound'):
        evidence, events = schedule.get('evidence'), schedule['events']
        parameters = metadata['schedule_parameters']
        if not isinstance(evidence, list) or len(evidence) != len(events):
            raise ValueError('Incomplete target timing evidence')
        for event, item in zip(events, evidence, strict=True):
            if (not isinstance(event, dict) or not isinstance(item, dict)
                    or type(item.get('source_id')) is not int or item['source_id'] not in selected
                    or type(item.get('source_tick_ms')) is not int):
                raise ValueError('Invalid target timing evidence')
            params = parameters[selected.index(item['source_id'])]
            if not isinstance(params, dict):
                raise ValueError('Invalid target timing parameters')
            interval = item.get('source_interval')
            try:
                validate_crossing_intervals([interval], [item['source_tick_ms']],
                                            duration_ms=params['duration_ms'])
                bound = 'upper_ms' if mode == 'upper_bound' else 'lower_ms'
                expected_time = interval[bound] + params['delay_ms']
                if (type(event['time_ms']) not in (int, float)
                        or not math.isfinite(event['time_ms'])
                        or abs(event['time_ms'] - expected_time) > 1e-9):
                    raise ValueError('Target event time mismatch')
            except (KeyError, TypeError, OverflowError) as exc:
                raise ValueError('Invalid target timing evidence') from exc
        # Bind each event to the saved source, candidate compartment and explicit
        # synaptic parameters, not merely to a plausible timestamp.
        try:
            rebuilt = schedule_population_fragment_events(
                mapping['sources'], parameters, max_events=metadata['max_events'],
                timing_mode=mode)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError('Invalid target schedule provenance') from exc
        if rebuilt != schedule:
            raise ValueError('Target schedule provenance mismatch')
    probe = metadata.get('voltage_probe')
    if metadata.get('probe_format') not in (None, 2) or (
            metadata.get('probe_format') == 2 and probe is None):
        raise ValueError('Inconsistent voltage probe format')
    if probe is not None:
        events = schedule['events']
        if (not isinstance(probe, dict)
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
                or not events or not isinstance(events[0], dict)
                or events[0].get('child_node_id') != probe['child_node_id']
                or type(events[0].get('position')) not in (int, float)
                or not 0 <= events[0]['position'] <= 1
                or min(int(events[0]['position'] * probe['segments_per_edge']),
                       probe['segments_per_edge'] - 1) != probe['segment_index']):
            raise ValueError('Inconsistent voltage probe metadata')


def _validate_probe_presence(arrays, metadata):
    if ('probe_baseline_mv' in arrays) != (metadata.get('voltage_probe') is not None):
        raise ValueError('Inconsistent voltage probe arrays')


def _preview(arrays, metadata):
    """Preserve actual samples and extrema for all displayed signal components."""
    time = arrays['time_ms']
    names = ('source_neural_uv', 'target_neural_uv', 'target_delta_uv', 'neural_uv',
             'stimulus_artifact_uv', 'total_uv')
    if metadata.get('voltage_probe') is not None:
        names += PROBE_ARRAY_NAMES
    edges = np.linspace(0, len(time), min(250, len(time)) + 1, dtype=int)
    selected = set()
    for start, end in zip(edges[:-1], edges[1:], strict=True):
        selected.update((int(start), int(end - 1)))
        for name in names:
            selected.add(int(start + np.argmin(arrays[name][start:end])))
            selected.add(int(start + np.argmax(arrays[name][start:end])))
    positions = np.asarray(sorted(selected), dtype=int)
    result = {'samples': len(time), 'shown_samples': len(positions),
            'time_ms': time[positions].tolist(),
            **{name: arrays[name][positions].tolist() for name in names},
            'source_cells': metadata['source_cells'], 'target_cells': metadata['target_cells'],
            'target_id': metadata['mapping']['target_id'],
            'selected_source_ids': metadata['selected_source_ids'],
            'events': len(metadata['schedule']['events']),
            'units': {'time_ms': 'ms', 'signal': 'µV'},
            'limitations': ['Односторонний повтор без обратной связи с сетью.',
                            'Физическая запись ограничена указанными клетками.',
                            'Параметры синапсов и тканей не откалиброваны.']}
    if metadata.get('voltage_probe') is not None:
        result['voltage_probe'] = metadata['voltage_probe']
        if metadata.get('probe_format') == 2:
            result['probe_morphology_sha256'] = metadata['mapping']['target_morphology_sha256']
    if metadata['schedule'].get('timing_mode') in ('upper_bound', 'lower_bound'):
        result['timing_mode'] = metadata['schedule']['timing_mode']
    return result


def write_target_replay(result, output: Path, *, execution_provenance=None):
    """Write a new result without overwriting prior files; hashes do not validate biology."""
    replay, recording = result['replay'], result['recording']
    arrays = {key: np.asarray(recording[key], dtype=float) for key in ARRAY_NAMES[:6]}
    arrays['target_baseline_uv'] = np.asarray(replay['baseline_neural_uv'], dtype=float)
    arrays['target_delta_uv'] = np.asarray(replay['delta_neural_uv'], dtype=float)
    probe = replay.get('voltage_probe')
    if probe is not None:
        if (not isinstance(probe, dict)
                or not np.array_equal(probe.get('time_ms'), arrays['time_ms'])):
            raise ValueError('Invalid voltage probe time grid')
        arrays['probe_baseline_mv'] = np.asarray(probe['baseline_mv'], dtype=float)
        arrays['probe_active_mv'] = np.asarray(probe['active_mv'], dtype=float)
    _validate(arrays)
    metadata = {key: result[key] for key in ('source_configuration_sha256', 'source_manifest',
        'source_population_ids', 'selected_source_ids', 'schedule_parameters',
        'max_target_distance_um', 'max_events', 'interpretation')}
    metadata.update({key: replay[key] for key in ('mapping', 'schedule', 'recording',
        'voltage_range_mv', 'baseline_provenance', 'active_provenance', 'interpretation')})
    # Keep the overall and target-specific scope distinguishable.
    metadata['target_interpretation'] = metadata.pop('interpretation')
    metadata['interpretation'] = result['interpretation']
    metadata['source_cells'], metadata['target_cells'] = (recording['source_cells'],
                                                           recording['target_cells'])
    if probe is not None:
        metadata['probe_format'] = 2
        metadata['voltage_probe'] = {key: probe[key] for key in (
            'child_node_id', 'segment_index', 'segments_per_edge', 'segment_center',
            'interpretation')}
    if execution_provenance is not None:
        if (not isinstance(execution_provenance, dict)
                or set(execution_provenance) != {'configuration_sha256', 'source_package_sha256',
                                                 'source_manifest_sha256'}
                or any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value)
                       for value in execution_provenance.values())):
            raise ValueError('Invalid target execution provenance')
        metadata['execution'] = dict(execution_provenance)
    _validate_metadata(metadata)
    _validate_probe_presence(arrays, metadata)
    preview_bytes = _json(_preview(arrays, metadata))
    meta_bytes = _json(metadata)
    stream = io.BytesIO()
    np.savez_compressed(stream, **arrays)
    signal_bytes = stream.getvalue()
    if max(len(meta_bytes), len(signal_bytes), len(preview_bytes)) > MAX_BYTES:
        raise ValueError('Target replay archive exceeds size limit')
    files = {'target-model.json': meta_bytes, 'target-signals.npz': signal_bytes,
             'target-preview.json': preview_bytes}
    manifest = {'kind': 'experimental-one-way-target-replay', 'files': [
        {'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        for name, data in files.items()]}
    if execution_provenance is not None:
        manifest['configuration_sha256'] = execution_provenance['configuration_sha256']
    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        (output / name).write_bytes(data)
    (output / 'manifest.json').write_bytes(_json(manifest))
    return manifest


def read_target_replay(directory: Path):
    """Check bounded artifact hashes and internal signal equations."""
    manifest_path = directory / 'manifest.json'
    if (manifest_path.is_symlink() or not manifest_path.is_file()
            or manifest_path.stat().st_size > 65536):
        raise ValueError('Invalid target replay manifest')
    manifest = json.loads(manifest_path.read_bytes())
    rows = manifest.get('files') if isinstance(manifest, dict) else None
    if (not isinstance(manifest, dict)
            or manifest.get('kind') != 'experimental-one-way-target-replay'
            or not isinstance(rows, list)
            or [row.get('name') if isinstance(row, dict) else None for row in rows]
            != ['target-model.json', 'target-signals.npz', 'target-preview.json']):
        raise ValueError('Invalid target replay manifest')
    contents = {}
    for row in rows:
        path = directory / row['name']
        if (set(row) != {'name', 'bytes', 'sha256'} or path.is_symlink() or not path.is_file()
                or type(row['bytes']) is not int or not 0 < row['bytes'] <= MAX_BYTES
                or path.stat().st_size != row['bytes']):
            raise ValueError('Invalid target replay artifact')
        contents[row['name']] = path.read_bytes()
        if hashlib.sha256(contents[row['name']]).hexdigest() != row['sha256']:
            raise ValueError('Target replay checksum mismatch')
    raw = contents['target-signals.npz']
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        filenames = {x.filename for x in entries}
        expected = {f'{name}.npy' for name in ARRAY_NAMES}
        if (len(entries) != len(filenames) or sum(x.file_size for x in entries) > MAX_BYTES
                or filenames not in (
                    expected, expected | {f'{name}.npy' for name in PROBE_ARRAY_NAMES})):
            raise ValueError('Invalid target replay array archive')
    with np.load(io.BytesIO(raw), allow_pickle=False) as stored:
        names = ARRAY_NAMES + (PROBE_ARRAY_NAMES if 'probe_baseline_mv.npy' in filenames else ())
        if any(stored[name].dtype.kind not in 'fiu' for name in names):
            raise ValueError('Invalid target replay array type')
        arrays = {name: stored[name].astype(float) for name in names}
    _validate(arrays)
    def invalid_constant(value):
        raise ValueError(f'Invalid JSON number: {value}')
    metadata = json.loads(contents['target-model.json'], parse_constant=invalid_constant)
    _validate_metadata(metadata)
    _validate_probe_presence(arrays, metadata)
    execution = metadata.get('execution')
    if execution is not None and (
            not isinstance(execution, dict)
            or set(execution) != {'configuration_sha256', 'source_package_sha256',
                                  'source_manifest_sha256'}
            or any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value)
                   for value in execution.values())
            or manifest.get('configuration_sha256') != execution['configuration_sha256']):
        raise ValueError('Inconsistent target execution provenance')
    if execution is None and 'configuration_sha256' in manifest:
        raise ValueError('Missing target execution provenance')
    preview = json.loads(contents['target-preview.json'], parse_constant=invalid_constant)
    if preview != _preview(arrays, metadata):
        raise ValueError('Target replay preview mismatch')
    return {'manifest': manifest, 'metadata': metadata, 'arrays': arrays, 'preview': preview}
