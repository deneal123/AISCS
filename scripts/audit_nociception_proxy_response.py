"""Inspect provisional candidate events in a saved paired field-proxy result."""

import argparse
import json
from pathlib import Path

import numpy as np
from audit_nociception_connectivity import sha256


def audit(candidates_path, graph_dir, result_dir):
    candidates = json.loads(candidates_path.read_text(encoding='utf-8'))
    metadata = json.loads((result_dir / 'metadata.json').read_text(encoding='utf-8'))
    graph_manifest = graph_dir / 'manifest.json'
    graph = json.loads(graph_manifest.read_text(encoding='utf-8'))
    ids_path = graph_dir / 'ids.npy'
    network_path = result_dir / 'network.npz'
    if (graph['dataset'] != 'male-cns:v1.0'
            or metadata['graph_sha256'] != sha256(graph_manifest)
            or graph['arrays']['ids.npy'] != sha256(ids_path)
            or candidates['male_cns_annotations_sha256'] != sha256(graph_dir / 'neurons.feather')
            or metadata['network_sha256'] != sha256(network_path)):
        raise ValueError('Input provenance mismatch')
    ids = np.load(ids_path, mmap_mode='r', allow_pickle=False)
    if ids.ndim != 1 or np.any(ids[1:] <= ids[:-1]):
        raise ValueError('Graph IDs must be strictly increasing')
    selected = sorted({int(item['bodyId']) for item in candidates['candidates']})
    positions = np.searchsorted(ids, selected)
    if not selected or any(pos >= len(ids) or int(ids[pos]) != cell
                           for pos, cell in zip(positions, selected, strict=True)):
        raise ValueError('Candidate absent from graph')
    with np.load(network_path, allow_pickle=False) as network:
        if 'control_counts' not in network:
            raise ValueError('Paired control is required')
        counts, control = network['counts'], network['control_counts']
        if len(counts) != len(ids) or len(control) != len(ids):
            raise ValueError('Network count size mismatch')
        if np.any(counts < 0) or np.any(control < 0):
            raise ValueError('Negative event count')
        rows = [{'bodyId': body, 'events': int(counts[pos]),
                 'control_events': int(control[pos])}
                for body, pos in zip(selected, positions, strict=True)]
    field = metadata['field']
    return {'interpretation': ('Uncalibrated field proxy with predicted candidate identities; '
                               'not validated recruitment or nociception.'),
            'candidate_report_sha256': sha256(candidates_path),
            'graph_manifest_sha256': sha256(graph_manifest),
            'network_sha256': sha256(network_path),
            'metadata_sha256': sha256(result_dir / 'metadata.json'),
            'gain': metadata['gain'], 'seed': metadata['seed'],
            'waveform': metadata['waveform'],
            'field_configuration': field['field_audit']['configuration'],
            'excluded_from_direct_field': field['excluded_from_direct_field'],
            'candidates': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', type=Path, required=True)
    parser.add_argument('--graph', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(audit(args.candidates, args.graph, args.result), indent=2)
                           + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
