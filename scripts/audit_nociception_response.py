"""Inspect provisional cell candidates in a saved paired-control network result.

No result produced here verifies cross-dataset identity or nociception.
"""

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy as np


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def audit(candidates_path, graph_ids_path, archive_path):
    candidate_bytes = candidates_path.read_bytes()
    candidates = json.loads(candidate_bytes)
    ids_digest = hashlib.sha256(graph_ids_path.read_bytes()).hexdigest()
    ids = np.load(graph_ids_path, mmap_mode='r', allow_pickle=False)
    if ids.ndim != 1 or np.any(ids[1:] <= ids[:-1]):
        raise ValueError('Graph IDs must be strictly increasing')
    selected = sorted({int(row['bodyId']) for row in candidates['candidates']})
    if not selected:
        raise ValueError('No candidates')
    positions = np.searchsorted(ids, selected)
    if any(pos >= len(ids) or int(ids[pos]) != cell
           for pos, cell in zip(positions, selected, strict=True)):
        raise ValueError('Candidate missing from graph')
    archive_bytes = archive_path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        if manifest['kind'] != 'experimental-coupled-population':
            raise ValueError('Unexpected archive kind')
        entries = {entry['name']: entry for entry in manifest['files']}
        content = {name: archive.read(name) for name in ('model.json', 'arrays.npz')}
        for name, data in content.items():
            if len(data) != entries[name]['bytes'] or sha256_bytes(data) != entries[name]['sha256']:
                raise ValueError(f'Archive checksum mismatch: {name}')
    model = json.loads(content['model.json'])
    graph = model['network_metadata']['graph']
    if (graph['array_sha256']['ids.npy'] != ids_digest
            or graph['annotations_sha256'] != candidates['male_cns_annotations_sha256']):
        raise ValueError('Graph or candidate provenance mismatch')
    with np.load(io.BytesIO(content['arrays.npz']), allow_pickle=False) as arrays:
        offsets = arrays['sparse_offsets']
        indices = arrays['sparse_indices']
        values = arrays['sparse_values']
        counts = arrays['network_counts']
        duration = model['network_metadata']['duration_ms']
        if (len(offsets) != duration + 2 or int(offsets[0]) != 0
                or int(offsets[-1]) != len(indices) or len(indices) != len(values)
                or len(counts) != len(ids) or np.any(offsets[1:] < offsets[:-1])
                or np.any(indices < 0) or np.any(indices >= len(ids))
                or not np.isfinite(values).all()):
            raise ValueError('Invalid sparse network response')
        maxima = np.zeros(len(selected), dtype=np.float64)
        first_tick = [None] * len(selected)
        for tick in range(1, len(offsets)):
            start, end = int(offsets[tick - 1]), int(offsets[tick])
            sample_indices = indices[start:end]
            if len(np.unique(sample_indices)) != len(sample_indices):
                raise ValueError('Duplicate cell in sparse frame')
            matches = np.searchsorted(positions, sample_indices)
            valid = matches < len(positions)
            valid[valid] &= positions[matches[valid]] == sample_indices[valid]
            for index, value in zip(matches[valid], values[start:end][valid], strict=True):
                maxima[index] = max(maxima[index], abs(float(value)))
                if first_tick[index] is None:
                    first_tick[index] = tick - 1
        forced = set(model['forced_cell_ids'])
        rows = [{'bodyId': cell, 'forced_source': cell in forced,
                 'network_spikes': int(counts[pos]),
                 'max_abs_saved_delta_mv': float(maxima[i]),
                 'first_changed_saved_tick_ms': first_tick[i]}
                for i, (cell, pos) in enumerate(zip(selected, positions, strict=True))]
    return {'interpretation': 'Provisional candidates in an uncalibrated model; differences are not evidence of nociception or subjective pain.',
            'archive_sha256': sha256_bytes(archive_bytes),
            'candidates_sha256': sha256_bytes(candidate_bytes),
            'ids_sha256': ids_digest, 'archive_status': model['status'],
            'duration_ms': duration, 'candidates': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', type=Path, required=True)
    parser.add_argument('--graph-ids', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.candidates, args.graph_ids, args.archive)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
