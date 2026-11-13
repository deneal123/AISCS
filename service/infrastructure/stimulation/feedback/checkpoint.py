"""Integrity-checked, immutable snapshots for experimental feedback iterations.

Checksums detect accidental corruption; they do not authenticate the writer or
prove biological validity. A snapshot is not a published simulation result.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np

MAX_BYTES = 256 * 1024 * 1024


def _encode(value):
    def convert(item):
        if isinstance(item, np.ndarray):
            return item.tolist()
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError('Non-serializable checkpoint value')
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False, default=convert).encode('utf8')


def checkpoint_run_identity(source_manifest, index_manifest):
    """Bind snapshots to source, index, service Python code and solver versions."""
    if not isinstance(source_manifest, dict) or not isinstance(index_manifest, dict):
        raise ValueError('Missing checkpoint input manifests')
    root = Path(__file__).resolve().parents[3]
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*.py')):
        relative = path.relative_to(root).as_posix().encode('utf8')
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, 'big') + relative)
        digest.update(len(data).to_bytes(8, 'big') + data)
    versions = {}
    for package in ('numpy', 'scipy', 'numba', 'NEURON', 'LFPy'):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    identity = {'source_manifest': source_manifest, 'index_manifest': index_manifest,
                'service_sha256': digest.hexdigest(), 'versions': versions,
                'python': platform.python_version(), 'machine': platform.machine(),
                'system': platform.system()}
    return hashlib.sha256(_encode(identity)).hexdigest()


def validate_checkpoint(state, *, config, diagnostics, parameters, allow_partial_geometry,
                        run_identity):
    if (not isinstance(state, dict) or state.get('format') != 'population-feedback-checkpoint-v1'
            or state.get('configuration_sha256') != config.digest()
            or state.get('graph_sha256') != config.graph_manifest_sha256
            or not isinstance(run_identity, str) or not re.fullmatch(r'[a-f0-9]{64}', run_identity)
            or state.get('run_identity') != run_identity
            or state.get('allow_partial_geometry') is not allow_partial_geometry
            or state.get('parameters') != json.loads(_encode(parameters))
            or state.get('source_ids') != config.source_ids
            or not isinstance(state.get('history'), list) or not state['history']
            or not isinstance(state.get('local'), dict)
            or set(state['local']) != set(map(str, config.source_ids))):
        raise ValueError('Checkpoint identity mismatch')
    history = state['history']
    if any(not isinstance(row, dict) or row.get('iteration') != number
           or not isinstance(row.get('schedule_sha256'), str)
           or not re.fullmatch(r'[a-f0-9]{64}', row['schedule_sha256'])
           for number, row in enumerate(history, 1)):
        raise ValueError('Invalid checkpoint history')
    if len({row['schedule_sha256'] for row in history}) != len(history):
        raise ValueError('Duplicate checkpoint schedule')
    applied = state.get('applied_schedule')
    if applied is not None:
        if (not isinstance(applied, dict)
                or applied.get('graph_sha256') != config.graph_manifest_sha256
                or applied.get('source_ids') != config.source_ids
                or not isinstance(applied.get('events_by_target'), dict)
                or set(applied['events_by_target']) != set(map(str, config.source_ids))
                or any(not isinstance(events, list)
                       for events in applied['events_by_target'].values())
                or not isinstance(applied.get('provenance_by_target'), dict)
                or set(applied['provenance_by_target']) != set(map(str, config.source_ids))
                or any(not isinstance(applied['provenance_by_target'][str(body)], list)
                       or len(applied['provenance_by_target'][str(body)])
                       != len(applied['events_by_target'][str(body)]) for body in config.source_ids)
                or not isinstance(applied.get('target_morphology_sha256'), dict)
                or any(key not in set(map(str, config.source_ids))
                       or digest != diagnostics.get(int(key), {}).get('morphology_sha256')
                       for key, digest in applied['target_morphology_sha256'].items())
                or not isinstance(applied.get('unresolved'), list)
                or (applied['unresolved'] and not allow_partial_geometry)
                or type(applied.get('event_count')) is not int
                or not 0 <= applied['event_count'] <= 1_000_000
                or applied['event_count'] != sum(map(len, applied['events_by_target'].values()))
                or type(history[-1].get('input_events')) is not int
                or applied['event_count'] != history[-1].get('input_events')
                or type(applied.get('outside_window')) is not int
                or type(history[-1].get('outside_window')) is not int
                or applied.get('outside_window') != history[-1].get('outside_window')):
            raise ValueError('Invalid checkpoint applied schedule')
        if (any(not isinstance(row, dict) or not isinstance(row.get('stimulated_ticks_ms'), list)
                or any(type(tick) is not int or not 1 <= tick <= config.simulation.duration_ms
                       for tick in row['stimulated_ticks_ms']) for row in applied['unresolved'])
                or type(history[-1].get('unresolved_events')) is not int
                or sum(len(row['stimulated_ticks_ms']) for row in applied['unresolved'])
                != history[-1]['unresolved_events']):
            raise ValueError('Invalid checkpoint unresolved events')
        event_fields = {'child_node_id', 'position', 'time_ms', 'weight_us', 'tau1_ms',
                        'tau2_ms', 'reversal_mv'}
        evidence_fields = {'source_id', 'candidate_index', 'source_tick_ms'}
        observation_fields = {'target_position_8nm', 'target_distance_um'}
        provenance_digest = applied.get('provenance_sha256')
        if provenance_digest is not None:
            actual_digest = hashlib.sha256(json.dumps(
                applied['provenance_by_target'], sort_keys=True, separators=(',', ':'),
                allow_nan=False).encode()).hexdigest()
            if provenance_digest != actual_digest:
                raise ValueError('Checkpoint schedule provenance differs')
        kinetic_fields = ('weight_us', 'tau1_ms', 'tau2_ms', 'reversal_mv')
        choices = list(parameters.values())
        for body in config.source_ids:
            events = applied['events_by_target'][str(body)]
            evidence = applied['provenance_by_target'][str(body)]
            for event, origin in zip(events, evidence, strict=True):
                if (not isinstance(event, dict) or set(event) != event_fields
                        or type(event['child_node_id']) is not int or event['child_node_id'] <= 0
                        or any(type(event[key]) not in (int, float) or not math.isfinite(event[key])
                               for key in event_fields - {'child_node_id'})
                        or not 0 <= event['position'] <= 1
                        or not isinstance(origin, dict)
                        or set(origin) not in (evidence_fields,
                                               evidence_fields | observation_fields,
                                               evidence_fields | observation_fields
                                               | {'source_position_8nm'})
                        or (observation_fields <= set(origin) and (
                            provenance_digest is None
                            or not isinstance(origin['target_position_8nm'], list)
                            or len(origin['target_position_8nm']) != 3
                            or any(type(value) is not int or value < 0
                                   for value in origin['target_position_8nm'])
                            or type(origin['target_distance_um']) not in (int, float)
                            or not math.isfinite(origin['target_distance_um'])
                            or origin['target_distance_um'] < 0))
                        or ('source_position_8nm' in origin and (
                            not isinstance(origin['source_position_8nm'], list)
                            or len(origin['source_position_8nm']) != 3
                            or any(type(value) is not int or value < 0
                                   for value in origin['source_position_8nm'])))
                        or type(origin['source_id']) is not int
                        or not 0 < origin['source_id'] < 2**63
                        or origin['source_id'] == body
                        or type(origin['candidate_index']) is not int
                        or origin['candidate_index'] < 0
                        or type(origin['source_tick_ms']) is not int
                        or not 1 <= origin['source_tick_ms'] <= config.simulation.duration_ms
                        or event['time_ms'] != origin['source_tick_ms'] + 2
                        or event['time_ms'] >= config.simulation.duration_ms
                        or not any(isinstance(choice, dict) and all(
                            event[key] == choice.get(key) for key in kinetic_fields)
                            for choice in choices)):
                    raise ValueError('Invalid checkpoint schedule event provenance')
        signature = hashlib.sha256(json.dumps(
            {'events': applied['events_by_target'], 'unresolved': applied['unresolved']},
            sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        if signature != history[-1]['schedule_sha256']:
            raise ValueError('Checkpoint applied schedule differs')
    edges = Counter()
    for body in config.source_ids:
        original = diagnostics.get(body)
        if not isinstance(original, dict) or not isinstance(original.get('candidates'), list):
            raise ValueError('Missing source diagnostics')
        expected = Counter((row['partner_id'], *row['source_position_8nm'])
                           for row in original['candidates'] if row['included_in_graph']
                           and (config.allow_partial_geometry is not True
                                or row['centerline_distance_um'] <= config.max_distance_um))
        rows = state['local'][str(body)]
        if not isinstance(rows, list) or len(rows) != sum(expected.values()):
            raise ValueError('Incomplete checkpoint source')
        observed = Counter()
        for row in rows:
            if (not isinstance(row, dict)
                    or set(row) != {'partner_id', 'source_position_8nm', 'stimulated_ticks_ms'}
                    or not isinstance(row['partner_id'], str) or not row['partner_id'].isascii()
                    or not row['partner_id'].isdigit() or row['partner_id'].startswith('0')
                    or not isinstance(row['source_position_8nm'], list)
                    or len(row['source_position_8nm']) != 3
                    or any(type(value) is not int for value in row['source_position_8nm'])
                    or not isinstance(row['stimulated_ticks_ms'], list)
                    or any(type(tick) is not int or not 1 <= tick <= config.simulation.duration_ms
                           for tick in row['stimulated_ticks_ms'])
                    or any(a >= b for a, b in zip(row['stimulated_ticks_ms'],
                                                   row['stimulated_ticks_ms'][1:], strict=False))):
                raise ValueError('Invalid checkpoint source event')
            observed[(row['partner_id'], *row['source_position_8nm'])] += 1
            for tick in row['stimulated_ticks_ms']:
                edges[(body, int(row['partner_id']), tick)] += 1
        if observed != expected:
            raise ValueError('Checkpoint source coordinates differ')
    expected_edges = [{'source_id': source, 'target_id': target, 'tick': tick, 'count': count}
                      for (source, target, tick), count in sorted(edges.items())]
    supplied = state.get('edges')
    if (not isinstance(supplied, list) or len(supplied) != len(expected_edges)
            or sorted(supplied, key=lambda row: (row['source_id'], row['target_id'], row['tick']))
               != expected_edges):
        raise ValueError('Checkpoint edge events differ')
    recording = state.get('recording')
    if not isinstance(recording, dict) or recording.get('cells') != len(config.source_ids):
        raise ValueError('Invalid checkpoint recording')
    names = ('time_ms', 'neural_uv', 'stimulus_artifact_uv', 'stimulus_fraction', 'total_uv')
    arrays = [recording.get(name) for name in names]
    dt = config.simulation.dt_ms
    expected_samples = round(config.simulation.duration_ms / dt) + 1
    if (any(not isinstance(arr, list) or len(arr) < 2 for arr in arrays)
            or len(arrays[0]) != expected_samples
            or any(len(arr) != len(arrays[0]) for arr in arrays)
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   for arr in arrays for value in arr)
            or any(a >= b for a, b in zip(arrays[0], arrays[0][1:], strict=False))
            or any(not math.isclose(value, index * dt, rel_tol=0, abs_tol=1e-7)
                   for index, value in enumerate(arrays[0]))
            or not math.isclose(arrays[0][0], 0, abs_tol=1e-8)
            or not math.isclose(arrays[0][-1], config.simulation.duration_ms, abs_tol=1e-8)
            or any(not math.isclose(total, neural + artifact, rel_tol=1e-10, abs_tol=1e-10)
                   for neural, artifact, total in zip(arrays[1], arrays[2], arrays[4],
                                                     strict=True))):
        raise ValueError('Inconsistent checkpoint recording')
    return state


def write_checkpoint(path: Path, state):
    """Atomically publish a fully written snapshot without overwriting an existing one."""
    payload = _encode(state)
    envelope = _encode({'sha256': hashlib.sha256(payload).hexdigest(),
                        'payload': json.loads(payload)}) + b'\n'
    if len(envelope) > MAX_BYTES:
        raise ValueError('Checkpoint exceeds size limit')
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(envelope)
            stream.flush()
            os.fsync(stream.fileno())
        # Linking publishes the complete inode atomically and fails if the
        # immutable target already exists, including concurrent writers.
        os.link(temporary, path)
    finally:
        os.unlink(temporary)
    return hashlib.sha256(envelope).hexdigest()


def read_checkpoint(path: Path, *, config, diagnostics, parameters, allow_partial_geometry,
                    run_identity):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError('Invalid checkpoint file')
    try:
        envelope = json.loads(path.read_bytes(), parse_constant=lambda _: (_ for _ in ()).throw(
            ValueError('Non-finite checkpoint')))
        if (not isinstance(envelope, dict) or set(envelope) != {'sha256', 'payload'}
                or envelope['sha256'] != hashlib.sha256(_encode(envelope['payload'])).hexdigest()):
            raise ValueError('Checkpoint checksum mismatch')
        return validate_checkpoint(envelope['payload'], config=config, diagnostics=diagnostics,
            parameters=parameters, allow_partial_geometry=allow_partial_geometry,
            run_identity=run_identity)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid checkpoint') from exc
