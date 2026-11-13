"""Compare field masks in the uncalibrated network; not a biological experiment."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from service.infrastructure.connectome.dataset import load_registered_graph
from service.infrastructure.connectome.field_proxy import run_field_proxy
from service.infrastructure.stimulation.field.summary_verified import verified_descriptors


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def positions(ids, report):
    selected = sorted({int(row['bodyId']) for row in report['candidates']})
    indexes = np.searchsorted(ids, selected)
    if not selected or any(i >= len(ids) or int(ids[i]) != body
                           for i, body in zip(indexes, selected, strict=True)):
        raise ValueError('Candidate absent from graph')
    return selected, indexes


def event_timeline(run, selected_positions):
    event_positions = run['spike_neurons']
    times = run['spike_times_ms']
    if event_positions.shape != times.shape or not np.isfinite(times).all():
        raise ValueError('Invalid event timeline')
    selected = np.isin(event_positions, selected_positions)
    unique, counts = np.unique(times[selected], return_counts=True)
    return [{'time_ms': float(time), 'events': int(count)}
            for time, count in zip(unique, counts, strict=True)]


def ablate_outgoing(graph, selected_positions, targets=None):
    """Return a private graph copy with outgoing weights from candidates removed."""
    ablated = copy.copy(graph)
    ablated.counts = np.array(graph.counts, copy=True)
    for position in selected_positions:
        start, end = int(graph.ptr[position]), int(graph.ptr[position + 1])
        if targets is None:
            ablated.counts[start:end] = 0
        else:
            mask = np.isin(graph.posts[start:end], targets)
            ablated.counts[start:end][mask] = 0
    return ablated


def probe(graph_path, field_path, sensory_path, ascending_path, gain, seed, events_output=None):
    graph = load_registered_graph(graph_path)
    sensory = json.loads(sensory_path.read_text(encoding='utf-8'))
    ascending = json.loads(ascending_path.read_text(encoding='utf-8'))
    for report in (sensory, ascending):
        if report['male_cns_annotations_sha256'] != graph.provenance['annotations_sha256']:
            raise ValueError('Candidate annotations mismatch')
    sensory_ids, sensory_pos = positions(graph.ids, sensory)
    ascending_ids, ascending_pos = positions(graph.ids, ascending)
    desc, provenance = verified_descriptors(field_path, graph.ids,
        graph.provenance['manifest_sha256'], allow_partial_geometry=True,
        allow_missing_curvature=True, allow_contact_exclusion=True)
    waveform = [0] * 5 + [1] * 10 + [0] * 5
    candidate_field = np.zeros_like(desc)
    candidate_field[sensory_pos] = desc[sensory_pos]
    other_field = desc.copy()
    other_field[sensory_pos] = 0
    if not np.array_equal(candidate_field + other_field, desc):
        raise ValueError('Field mask decomposition mismatch')
    ablated_graph = ablate_outgoing(graph, sensory_pos)
    direct_ablated_graph = ablate_outgoing(graph, sensory_pos, ascending_pos)
    results = {}
    for name, field, selected_graph in [
        ('all', desc, graph), ('candidate_only', candidate_field, graph),
        ('candidate_only_no_outgoing', candidate_field, ablated_graph),
        ('candidate_only_no_direct_ascending', candidate_field, direct_ablated_graph),
        ('without_candidates', other_field, graph), ('zero', np.zeros_like(desc), graph),
    ]:
        run = run_field_proxy(selected_graph, descriptor=field, waveform=waveform,
                              gain=gain, seed=seed)
        if name == 'candidate_only' and events_output is not None:
            np.savez_compressed(events_output, spike_neurons=run['spike_neurons'],
                                spike_times_ms=run['spike_times_ms'])
        counts = run['counts']
        results[name] = {
            'total_events': int(counts.sum(dtype=np.int64)),
            'sensory_events': int(counts[sensory_pos].sum(dtype=np.int64)),
            'ascending_events': int(counts[ascending_pos].sum(dtype=np.int64)),
            'sensory_timeline': event_timeline(run, sensory_pos),
            'ascending_timeline': event_timeline(run, ascending_pos),
            'ascending_active_ids': [body for body, i in zip(ascending_ids, ascending_pos,
                                                              strict=True) if counts[i] > 0],
            'events_sha256': hashlib.sha256(run['spike_neurons'].tobytes()
                                            + run['spike_times_ms'].tobytes()).hexdigest(),
        }
    return {'interpretation': 'Counterfactual field masks, uncalibrated model; not nociception.',
            'graph_sha256': graph.provenance['manifest_sha256'],
            'field_sha256': provenance['file_sha256'],
            'field_configuration': provenance['field_audit']['configuration'],
            'field_exclusions': provenance['excluded_from_direct_field'],
            'contact_exclusions': provenance['excluded_contact_intersections'],
            'sensory_report_sha256': sha256(sensory_path),
            'ascending_report_sha256': sha256(ascending_path),
            'sensory_ids': sensory_ids, 'gain': gain, 'seed': seed,
            'waveform': waveform, 'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph', type=Path, required=True)
    parser.add_argument('--field', type=Path, required=True)
    parser.add_argument('--sensory', type=Path, required=True)
    parser.add_argument('--ascending', type=Path, required=True)
    parser.add_argument('--gain', type=float, required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--events-output', type=Path)
    args = parser.parse_args()
    report = probe(args.graph, args.field, args.sensory, args.ascending, args.gain, args.seed,
                   args.events_output)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
