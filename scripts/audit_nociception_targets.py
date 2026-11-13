"""Rank annotated ascending targets of provisional MaleCNS sensory candidates.

These are graph-derived hypotheses, not verified nociceptive pathway labels.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow.feather as feather
from audit_nociception_connectivity import audit as audit_graph
from audit_nociception_connectivity import sha256


def audit(candidate_report, graph_dir):
    verified = audit_graph(candidate_report, graph_dir)
    candidate_data = json.loads(candidate_report.read_text(encoding='utf-8'))
    annotations = feather.read_table(graph_dir / 'neurons.feather',
                                     columns=['bodyId', 'superclass', 'type', 'mancBodyid',
                                              'mancGroup', 'mancType']).to_pylist()
    by_id = {row['bodyId']: row for row in annotations}
    if len(by_id) != len(annotations):
        raise ValueError('Duplicate annotation IDs')
    ids = np.load(graph_dir / 'ids.npy', mmap_mode='r', allow_pickle=False)
    ptr = np.load(graph_dir / 'ptr.npy', mmap_mode='r', allow_pickle=False)
    posts = np.load(graph_dir / 'posts.npy', mmap_mode='r', allow_pickle=False)
    counts = np.load(graph_dir / 'counts.npy', mmap_mode='r', allow_pickle=False)
    if len(ids) != len(annotations) or set(map(int, ids)) != set(by_id):
        raise ValueError('Graph and annotation IDs differ')
    # These explicitly enumerated classes are a proxy for sensory input, not
    # a claim of cross-dataset equivalence with the author's neuPrint query.
    sensory_classes = {'vnc_sensory', 'cb_sensory', 'ol_sensory', 'sensory_ascending'}
    sensory_totals = np.zeros(len(ids), dtype=np.int64)
    total_totals = np.zeros(len(ids), dtype=np.int64)
    for start in range(0, len(posts), 1_000_000):
        end = min(start + 1_000_000, len(posts))
        total_totals += np.bincount(posts[start:end], weights=counts[start:end],
                                    minlength=len(ids)).astype(np.int64)
    for idx, cell in enumerate(ids):
        if by_id[int(cell)]['superclass'] in sensory_classes:
            start, end = int(ptr[idx]), int(ptr[idx + 1])
            np.add.at(sensory_totals, posts[start:end], counts[start:end])
    incoming = defaultdict(list)
    for row in candidate_data['candidates']:
        source = int(row['bodyId'])
        idx = int(np.searchsorted(ids, source))
        for target_index, count in zip(posts[ptr[idx]:ptr[idx + 1]],
                                       counts[ptr[idx]:ptr[idx + 1]], strict=True):
            target = int(ids[target_index])
            annotation = by_id.get(target)
            if annotation is None:
                raise ValueError('Graph target missing annotation')
            if annotation['superclass'] == 'ascending_neuron':
                incoming[target].append({'source_bodyId': source,
                                         'source_mancBodyid': row['mancBodyid'],
                                         'synapses': int(count)})
    result = []
    for target, edges in incoming.items():
        annotation = by_id[target]
        position = int(np.searchsorted(ids, target))
        sensory_total = int(sensory_totals[position])
        all_total = int(total_totals[position])
        candidate_total = sum(e['synapses'] for e in edges)
        if candidate_total > sensory_total or sensory_total > all_total:
            raise ValueError('Candidate input is inconsistent with sensory annotation')
        result.append({**annotation,
                       'total_synapses_from_candidates': candidate_total,
                       'total_sensory_synapses': sensory_total,
                       'total_incoming_synapses': all_total,
                       'candidate_share_sensory': candidate_total / sensory_total,
                       'candidate_share_all': candidate_total / all_total,
                       'candidate_sources': len(edges),
                       'edges_ge_4_synapses': sum(e['synapses'] >= 4 for e in edges),
                       'inputs': sorted(edges, key=lambda edge: edge['source_bodyId'])})
    result.sort(key=lambda row: (-row['total_synapses_from_candidates'], row['bodyId']))
    return {'interpretation': ('Predicted source candidates and annotated ascending targets; '
                               'not verified identity, nociception, or transmission.'),
            'candidate_report_sha256': sha256(candidate_report),
            'graph_manifest_sha256': verified['graph_manifest_sha256'],
            'male_cns_annotations_sha256': candidate_data['male_cns_annotations_sha256'],
            'sensory_superclasses': sorted(sensory_classes),
            'candidate_count': verified['candidate_count'],
            'target_count': len(result),
            'candidates': [{'bodyId': row['bodyId']} for row in result],
            'targets': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', type=Path, required=True)
    parser.add_argument('--graph', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.candidates, args.graph)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8')


if __name__ == '__main__':
    main()
