"""Create a separate self-checking model-state contrast artifact pair."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np

from service.application.field.state_contrast import contrast_verified_field_run
from service.infrastructure.connectome.state_contrast_export import (
    decode_state_contrast,
    encode_state_contrast,
)


def export_field_state_contrast(source: Path, output: Path, graph, *, sample_cell_ids,
                                expected_manifest_sha256):
    """Write a fresh directory; never alter the source or overwrite another output."""
    source, output = source.resolve(), output.resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError('State contrast output must be separate from the source')
    result = contrast_verified_field_run(source, graph, sample_cell_ids=sample_cell_ids,
                                         expected_manifest_sha256=expected_manifest_sha256)
    binary, description = encode_state_contrast(result)
    decode_state_contrast(binary, description,
        expected_field_manifest_sha256=expected_manifest_sha256,
        expected_graph_manifest_sha256=graph.provenance['manifest_sha256'],
        expected_graph_sha256=result['provenance']['graph_sha256'], graph_ids=graph.ids)
    description_bytes = (json.dumps(description, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')) + '\n').encode('utf-8')
    files = {'state-contrast.bin': binary, 'state-contrast.json': description_bytes}
    manifest = {'format': 'lif-state-contrast-manifest-v1', 'files': [
        {'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        for name, data in sorted(files.items())]}
    output.mkdir(parents=False, exist_ok=False)
    try:
        for name, data in files.items():
            (output / name).write_bytes(data)
        (output / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True) + '\n',
                                               encoding='utf-8', newline='\n')
    except BaseException:
        shutil.rmtree(output)
        raise
    return manifest


def load_field_state_contrast(output: Path, graph, *, expected_manifest_sha256,
                              expected_field_manifest_sha256, expected_graph_sha256):
    """Verify a caller-authenticated result manifest and all encoded data."""
    raw = (output / 'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
        raise ValueError('State contrast manifest does not match trusted digest')
    manifest = json.loads(raw)
    files = manifest.get('files') if isinstance(manifest, dict) else None
    if (not isinstance(manifest, dict) or manifest.get('format') != 'lif-state-contrast-manifest-v1'
            or not isinstance(files, list) or len(files) != 2
            or any(not isinstance(item, dict) for item in files)
            or {item.get('name') for item in files}
            != {'state-contrast.bin', 'state-contrast.json'}):
        raise ValueError('Invalid state contrast manifest')
    contents = {}
    for item in files:
        limit = 32_000_000 if item['name'].endswith('.bin') else 16384
        size = item.get('bytes')
        if type(size) is not int or not 1 <= size <= limit:
            raise ValueError('Invalid state contrast artifact size')
        path = output / item['name']
        if path.stat().st_size != size:
            raise ValueError('State contrast artifact size mismatch')
        data = path.read_bytes()
        if len(data) != size or hashlib.sha256(data).hexdigest() != item.get('sha256'):
            raise ValueError('State contrast artifact checksum mismatch')
        contents[item['name']] = data
    description = json.loads(contents['state-contrast.json'])
    return decode_state_contrast(contents['state-contrast.bin'], description,
        expected_field_manifest_sha256=expected_field_manifest_sha256,
        expected_graph_manifest_sha256=graph.provenance['manifest_sha256'],
        expected_graph_sha256=expected_graph_sha256, graph_ids=graph.ids)


def bundle_field_state_contrast(source: Path, graph, *, duration_ms):
    """Attach a bounded contrast and its original source manifest to a fresh result."""
    if type(duration_ms) is not int or not 1 <= duration_ms <= 1000:
        raise ValueError('Invalid contrast duration')
    limit = min(graph.size, 4_000_000 // (duration_ms + 1))
    indices = np.linspace(0, graph.size - 1, num=limit, dtype=np.int64)
    ids = [int(graph.ids[index]) for index in indices]
    source_manifest = (source / 'manifest.json').read_bytes()
    source_sha = hashlib.sha256(source_manifest).hexdigest()
    names = ('state-contrast.bin', 'state-contrast.json', 'state-source-manifest.json')
    if any((source / name).exists() for name in names):
        raise FileExistsError('State contrast already exists')
    with tempfile.TemporaryDirectory(prefix='state-contrast-', dir=source.parent) as temporary:
        output = Path(temporary) / 'output'
        export_field_state_contrast(source, output, graph, sample_cell_ids=ids,
                                    expected_manifest_sha256=source_sha)
        payloads = {'state-contrast.bin': (output / 'state-contrast.bin').read_bytes(),
                    'state-contrast.json': (output / 'state-contrast.json').read_bytes(),
                    'state-source-manifest.json': source_manifest}
        written = []
        try:
            for name, payload in payloads.items():
                with (source / name).open('xb') as stream:
                    written.append(source / name)
                    stream.write(payload)
        except BaseException:
            for path in written:
                path.unlink(missing_ok=True)
            raise
    return [{'name': name, 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
            for name, payload in payloads.items()]
