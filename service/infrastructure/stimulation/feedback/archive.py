"""Bounded, integrity-checked storage of a coupled population result.

Checksums detect corruption and bind the files to the separately verified source;
they are not signatures and do not establish biological validity.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import numpy as np

from service.application.feedback.validation import validate_population_feedback
from service.infrastructure.stimulation.feedback.discretization_archive import _normalize_receipt
from service.infrastructure.stimulation.population.archive import (
    load_verified_fragment_population,
)

MAX_BYTES = 256 * 1024 * 1024
RECORDING = ('time_ms', 'neural_uv', 'stimulus_artifact_uv', 'stimulus_fraction', 'total_uv')
NETWORK = ('spike_neurons', 'spike_times_ms', 'counts', 'final_voltage_relative_mv',
           'final_synaptic_drive_mv')
SPARSE = ('offsets', 'indices', 'values')
ARRAYS = tuple('recording_' + name for name in RECORDING) + tuple(
    'network_' + name for name in NETWORK) + tuple('sparse_' + name for name in SPARSE)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf8')


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def write_population_feedback(result, output: Path, *, source_directory: Path, graph,
                              parameters, allow_partial_geometry, discretization_context=None):
    source = load_verified_fragment_population(source_directory, graph)
    validate_population_feedback(result, graph, source, parameters=parameters,
                                 allow_partial_geometry=allow_partial_geometry,
                                 discretization_context=discretization_context)
    recording, network = result['recording'], result['network']
    arrays = {'recording_' + name: np.asarray(recording[name]) for name in RECORDING}
    arrays.update({'network_' + name: np.asarray(network[name]) for name in NETWORK})
    arrays.update({'sparse_' + name: np.asarray(network['sparse_delta'][name]) for name in SPARSE})
    if sum(array.nbytes + 1024 for array in arrays.values()) > MAX_BYTES:
        raise ValueError('Coupled arrays exceed size limit')
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    binary = buffer.getvalue()
    metadata = {'format': 'experimental-coupled-population-v1',
        'source_manifest_sha256': _digest(_json(source['manifest'])),
        'parameters': json.loads(_json(parameters)),
        'allow_partial_geometry': allow_partial_geometry,
        'status': result['status'], 'feedback_alignment': result['feedback_alignment'],
        'iterations': result['iterations'], 'schedule': result['schedule'],
        'physical_source_output': result['physical_source_output'],
        'recording_cells': recording['cells'], 'network_metadata': network['metadata'],
        'forced_cell_ids': network['forced_cell_ids'],
        'limitations': ['Physical recording covers only the source population.',
                        'The remaining graph uses an uncalibrated LIF model.',
                        'No biological or clinical validation is implied.']}
    if discretization_context is not None:
        metadata['format'] = 'experimental-coupled-population-v2'
        metadata['discretization_policy'] = discretization_context['policy']
        metadata['discretization_receipt'] = result.get('discretization_receipt') or (
            result['discretization_receipts'][-1])
    meta = _json(metadata)
    manifest = _json({'kind': 'experimental-coupled-population', 'files': [
        {'name': name, 'bytes': len(data), 'sha256': _digest(data)}
        for name, data in (('model.json', meta), ('arrays.npz', binary))]})
    if any(not 0 < len(data) <= MAX_BYTES for data in (manifest, meta, binary)):
        raise ValueError('Coupled artifact exceeds size limit')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('manifest.json', manifest)
        archive.writestr('model.json', meta)
        archive.writestr('arrays.npz', binary)
    data = stream.getvalue()
    if len(data) > MAX_BYTES:
        raise ValueError('Coupled archive exceeds size limit')
    with output.open('xb') as destination:
        destination.write(data)
        destination.flush()
        os.fsync(destination.fileno())
    return _digest(data)


def read_population_feedback(path: Path, *, source_directory: Path, graph, parameters,
                             allow_partial_geometry, discretization_context=None):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError('Invalid coupled archive')
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [item.filename for item in entries]
        if (names != ['manifest.json', 'model.json', 'arrays.npz']
                or sum(item.file_size for item in entries) > MAX_BYTES):
            raise ValueError('Invalid coupled archive entries')
        files = {name: archive.read(name) for name in names}
    def parse(data):
        return json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(
            ValueError('Non-finite coupled metadata')))
    manifest = parse(files['manifest.json'])
    expected = [{'name': name, 'bytes': len(files[name]), 'sha256': _digest(files[name])}
                for name in ('model.json', 'arrays.npz')]
    if manifest != {'kind': 'experimental-coupled-population', 'files': expected}:
        raise ValueError('Coupled archive checksum mismatch')
    meta = parse(files['model.json'])
    source = load_verified_fragment_population(source_directory, graph)
    expected_format = ('experimental-coupled-population-v2' if discretization_context is not None
                       else 'experimental-coupled-population-v1')
    if (not isinstance(meta, dict) or meta.get('format') != expected_format
            or meta.get('source_manifest_sha256') != _digest(_json(source['manifest']))
            or meta.get('parameters') != json.loads(_json(parameters))
            or meta.get('allow_partial_geometry') is not allow_partial_geometry
            or (discretization_context is None and (
                'discretization_policy' in meta or 'discretization_receipt' in meta))
            or (discretization_context is not None
                and (not isinstance(discretization_context, dict)
                     or meta.get('discretization_policy')
                        != discretization_context.get('policy')))):
        raise ValueError('Coupled archive provenance mismatch')
    raw = files['arrays.npz']
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if (len(entries) != len(ARRAYS) or {x.filename for x in entries} !=
                {name + '.npy' for name in ARRAYS}
                or sum(x.file_size for x in entries) > MAX_BYTES):
            raise ValueError('Invalid coupled arrays')
    with np.load(io.BytesIO(raw), allow_pickle=False) as stored:
        arrays = {name: stored[name] for name in ARRAYS}
    physical = meta['physical_source_output']
    for key in ('source_morphology_sha256', 'candidate_events_by_source'):
        physical[key] = {int(body): value for body, value in physical[key].items()}
    schedule = meta['schedule']
    for key in ('events_by_target', 'target_morphology_sha256', 'provenance_by_target'):
        if key in schedule:
            schedule[key] = {int(body): value for body, value in schedule[key].items()}
    recording = {'cells': meta['recording_cells'],
                 **{name: arrays['recording_' + name] for name in RECORDING}}
    network = {'forced_cell_ids': meta['forced_cell_ids'], 'metadata': meta['network_metadata'],
               **{name: arrays['network_' + name] for name in NETWORK},
               'sparse_delta': {'status': 'recorded',
                                **{name: arrays['sparse_' + name] for name in SPARSE}}}
    result = {'status': meta['status'], 'feedback_alignment': meta['feedback_alignment'],
              'iterations': meta['iterations'], 'schedule': schedule, 'recording': recording,
              'physical_source_output': physical, 'network': network}
    if discretization_context is not None:
        result['discretization_receipt'] = _normalize_receipt(meta.get('discretization_receipt'))
    validate_population_feedback(result, graph, source, parameters=parameters,
                                 allow_partial_geometry=allow_partial_geometry,
                                 discretization_context=discretization_context)
    return result
