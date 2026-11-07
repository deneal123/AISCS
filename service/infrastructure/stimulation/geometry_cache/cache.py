"""Explicit construction and verified streaming of a morphology snapshot cache.

Building can take substantial time and disk space. It is never automatic.
An independently persisted manifest hash is required to read the cache. The
audited source index describes a snapshot, not the current contents of SWC files.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np

from service.infrastructure.connectome import morphology, morphology_repository
from service.infrastructure.stimulation import morphology_field, network_field
from service.infrastructure.stimulation.geometry_cache import chunk, index
from service.infrastructure.stimulation.network_field import _prepare_gpu_skeleton


def _producer_sha256():
    result = hashlib.sha256()
    for module in (morphology, morphology_repository, morphology_field, network_field,
                   chunk, index):
        result.update(module.__name__.encode() + b'\0' + Path(module.__file__).read_bytes())
    result.update(b'geometry_cache\0' + Path(__file__).read_bytes())
    return result.hexdigest()


def build_cache(directory: Path, *, graph_ids, graph_sha256: str, source_index: Path,
                source_audit: Path, morphology_directories, chunk_neurons=64, progress=None):
    """Build one complete cache explicitly; return its independently storable hash.

    No pre-existing directory is modified. The manifest appears only after all
    chunks are written; owned partial files are removed on failure.
    """
    if type(chunk_neurons) is not int or chunk_neurons <= 0:
        raise ValueError('Invalid cache chunk size')
    if progress is not None and not callable(progress):
        raise ValueError('Invalid cache progress callback')
    raw_ids = list(graph_ids)
    ids = [int(value) for value in raw_ids]
    sources, source_sha = index.audited_geometry_sources(source_index, source_audit,
                                                         raw_ids, graph_sha256)
    producer_sha = _producer_sha256()
    directory.mkdir(parents=False, exist_ok=False)
    owned, descriptors, pending, pending_vertices = [], [], [], 0

    def flush():
        nonlocal pending, pending_vertices
        if not pending:
            return
        name = f'chunk-{len(descriptors):06d}.bin'
        path = directory / name
        metadata = chunk.write_chunk(path, pending, audited_sources=sources)
        owned.append(path)
        descriptors.append({'name': name, **metadata})
        pending, pending_vertices = [], 0

    try:
        for position, body in enumerate(ids):
            entry = _prepare_gpu_skeleton((body, morphology_directories))
            if 'status' in entry:
                raise ValueError(f'Cannot cache morphology {body}: {entry["status"]}')
            vertices = len(entry['geometry'][0])
            if pending and (len(pending) >= chunk_neurons
                            or pending_vertices + vertices > chunk._MAX_VERTICES):
                flush()
            pending.append(entry)
            pending_vertices += vertices
            if progress is not None:
                progress(position + 1, len(ids))
        flush()
        if _producer_sha256() != producer_sha:
            raise ValueError('Geometry cache producer changed during build')
        metadata = {'format': 'malecns-packed-geometry-cache-v1', 'graph_sha256': graph_sha256,
                    'source_index_sha256': source_sha, 'producer_sha256': producer_sha,
                    'numpy_version': np.__version__, 'python_version': sys.version.split()[0],
                    'neurons': len(ids), 'vertices': sum(item['vertices'] for item in descriptors),
                    'chunks': descriptors,
                    'interpretation': 'verified morphology snapshot; not neural activation'}
        raw = (json.dumps(metadata, sort_keys=True, separators=(',', ':'), allow_nan=False)
               + '\n').encode('utf8')
        manifest_path = directory / 'manifest.json'
        with manifest_path.open('xb') as stream:
            owned.append(manifest_path)
            if stream.write(raw) != len(raw):
                raise OSError('Incomplete geometry cache manifest')
        return hashlib.sha256(raw).hexdigest()
    except BaseException:
        for path in reversed(owned):
            path.unlink(missing_ok=True)
        try:
            directory.rmdir()
        except OSError:
            pass  # Never remove files not created by this invocation.
        raise


def iter_cache(directory: Path, *, expected_manifest_sha256: str, graph_ids,
               graph_sha256: str, source_index: Path, source_audit: Path):
    """Verify a trusted manifest and stream bounded authenticated chunks."""
    if (not isinstance(expected_manifest_sha256, str)
            or not re.fullmatch(r'[a-f0-9]{64}', expected_manifest_sha256)):
        raise ValueError('Invalid geometry cache manifest identity')
    raw_ids = list(graph_ids)
    ids = [int(value) for value in raw_ids]
    sources, source_sha = index.audited_geometry_sources(source_index, source_audit,
                                                         raw_ids, graph_sha256)
    try:
        raw = (directory / 'manifest.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
            raise ValueError('Geometry cache manifest checksum mismatch')
        metadata = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Geometry cache manifest unavailable') from exc
    if (not isinstance(metadata, dict)
            or metadata.get('format') != 'malecns-packed-geometry-cache-v1'
            or metadata.get('graph_sha256') != graph_sha256
            or metadata.get('source_index_sha256') != source_sha
            or metadata.get('producer_sha256') != _producer_sha256()
            or type(metadata.get('neurons')) is not int or metadata['neurons'] != len(ids)
            or type(metadata.get('vertices')) is not int or metadata['vertices'] < 1
            or not isinstance(metadata.get('chunks'), list) or not metadata['chunks']):
        raise ValueError('Geometry cache manifest does not match source snapshot')
    ordered, vertices = [], 0
    for position, descriptor in enumerate(metadata['chunks']):
        if (not isinstance(descriptor, dict)
                or descriptor.get('name') != f'chunk-{position:06d}.bin'
                or not isinstance(descriptor.get('neurons'), list)
                or type(descriptor.get('vertices')) is not int):
            raise ValueError('Invalid geometry cache chunk list')
        try:
            ordered.extend(int(item['body_id']) for item in descriptor['neurons'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('Invalid geometry cache source list') from exc
        vertices += descriptor['vertices']
    if ordered != ids or vertices != metadata['vertices']:
        raise ValueError('Geometry cache is incomplete or out of order')
    for descriptor in metadata['chunks']:
        yield chunk.read_chunk(directory / descriptor['name'], descriptor, audited_sources=sources)
