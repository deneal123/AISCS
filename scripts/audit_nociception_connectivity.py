"""Inspect connectivity of *unverified* cross-dataset nociception candidates.

The input is the report from audit_nociception_candidates.py.  This script
does not establish cell identity, function, or a nociceptive response.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def audit(candidate_report, graph_dir):
    report = json.loads(candidate_report.read_text(encoding='utf-8'))
    manifest = json.loads((graph_dir / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('dataset') != 'male-cns:v1.0':
        raise ValueError('Expected male-cns:v1.0 graph')
    if sha256(graph_dir / 'neurons.feather') != report['male_cns_annotations_sha256']:
        raise ValueError('Candidate annotations do not match graph annotations')
    arrays = {}
    for name in ('ids', 'ptr', 'posts', 'counts'):
        path = graph_dir / f'{name}.npy'
        if sha256(path) != manifest['arrays'][path.name]:
            raise ValueError(f'Graph checksum mismatch: {path.name}')
        arrays[name] = np.load(path, mmap_mode='r', allow_pickle=False)
    ids, ptr, posts, counts = (arrays[k] for k in ('ids', 'ptr', 'posts', 'counts'))
    if len(ptr) != len(ids) + 1 or len(posts) != len(counts) or int(ptr[-1]) != len(posts):
        raise ValueError('Invalid graph dimensions')
    candidate_ids = sorted({int(row['bodyId']) for row in report['candidates']})
    if not candidate_ids:
        raise ValueError('Candidate set is empty')
    positions = np.searchsorted(ids, candidate_ids)
    if any(pos >= len(ids) or int(ids[pos]) != cell
           for pos, cell in zip(positions, candidate_ids, strict=True)):
        raise ValueError('Candidate missing from graph')
    totals = {}
    within = []
    candidate_set = set(candidate_ids)
    for cell, position in zip(candidate_ids, positions, strict=True):
        start, end = int(ptr[position]), int(ptr[position + 1])
        targets, weights = posts[start:end], counts[start:end]
        if np.any(targets < 0) or np.any(targets >= len(ids)):
            raise ValueError('Graph contains invalid target index')
        totals[cell] = {'outgoing_partners': int(end - start),
                        'outgoing_synapses': int(np.sum(weights, dtype=np.int64))}
        for target, weight in zip(targets, weights, strict=True):
            target_id = int(ids[target])
            if target_id in candidate_set:
                within.append({'source': cell, 'target': target_id, 'synapses': int(weight)})
    return {
        'interpretation': 'Predicted candidate matches only; anatomical graph edges, not validated nociceptive cells, functional transmission, or pain.',
        'candidate_report_sha256': sha256(candidate_report),
        'graph_manifest_sha256': sha256(graph_dir / 'manifest.json'),
        'dataset': manifest['dataset'],
        'candidate_count': len(candidate_ids),
        'candidate_outgoing_totals': totals,
        'edges_between_candidates': sorted(within, key=lambda item: (item['source'], item['target'])),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', type=Path, required=True)
    parser.add_argument('--graph', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.candidates, args.graph)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
