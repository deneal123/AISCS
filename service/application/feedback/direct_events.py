"""Stream verified physical-to-physical graph events from population batches.

The output is provisional until the iterator is exhausted without errors.
These events are model threshold crossings, not proof of biological spikes.
"""

from itertools import zip_longest

import numpy as np

from .outputs import merge_archived_source_events


def iter_direct_feedback(graph, expected_ids, batches, *, duration_ms):
    """Route complete source batches to physical targets without a LIF pass.

    Each input is a mapping of integer source IDs to the ``edge_events`` list
    returned by the population crossing collector. Source batches must cover
    every expected cell exactly once. The caller must stage output and discard
    it if iteration fails, including failures raised at end of iteration.
    """
    if (not isinstance(expected_ids, list) or not expected_ids
            or any(type(body) is not int or body <= 0 for body in expected_ids)
            or len(set(expected_ids)) != len(expected_ids)
            or type(duration_ms) is not int or duration_ms < 1):
        raise ValueError('Invalid direct feedback input')
    positions = np.searchsorted(graph.ids, expected_ids)
    if any(pos >= len(graph.ids) or int(graph.ids[pos]) != body
           for pos, body in zip(positions, expected_ids, strict=True)):
        raise ValueError('Unknown physical cell')
    selected = set(expected_ids)
    received = set()
    for batch in batches:
        if (not isinstance(batch, dict) or not batch
                or any(type(body) is not int or body not in selected for body in batch)
                or received.intersection(batch)):
            raise ValueError('Invalid or repeated physical source batch')
        output = []
        for body, events in batch.items():
            if not isinstance(events, list):
                raise ValueError('Invalid physical edge events')
            if not events:
                continue
            pre = int(np.searchsorted(graph.ids, body))
            start, end = int(graph.ptr[pre]), int(graph.ptr[pre + 1])
            seen, targets = set(), set()
            for event in events:
                if (not isinstance(event, dict)
                        or set(event) != {'source_id', 'target_id', 'tick', 'count'}
                        or any(type(value) is not int for value in event.values())
                        or event['source_id'] != body or event['target_id'] not in selected
                        or not 1 <= event['tick'] <= duration_ms or event['count'] <= 0):
                    raise ValueError('Invalid physical edge event')
                key = (event['target_id'], event['tick'])
                if key in seen:
                    raise ValueError('Duplicate physical edge event')
                seen.add(key)
                targets.add(event['target_id'])
            verified = {}
            if targets:
                target_positions = np.searchsorted(graph.ids, list(targets))
                matches = np.flatnonzero(np.isin(graph.posts[start:end], target_positions))
                for offset in matches:
                    target = int(graph.ids[int(graph.posts[start + offset])])
                    if target in verified:
                        raise ValueError('Physical edge is missing or ambiguous')
                    verified[target] = int(graph.counts[start + offset])
                if len(verified) != len(targets):
                    raise ValueError('Physical edge is missing or ambiguous')
            for event in events:
                target = event['target_id']
                if event['count'] > verified[target]:
                    raise ValueError('Physical edge count exceeds registered synapses')
                arrival = event['tick'] + 2
                output.append({'source_id': body, 'target_id': target,
                    'emission_tick_ms': event['tick'], 'delivery_tick_ms': arrival,
                    'synapse_count': event['count'], 'predicted_sign': int(graph.signs[pre]),
                    'kind': 'physical-source-edge', 'within_window': arrival <= duration_ms,
                    'affects_replay': arrival < duration_ms})
        received.update(batch)
        yield output
    if received != selected:
        raise ValueError('Incomplete physical source batches')


def iter_verified_source_feedback(graph, expected_ids, source_batches, *, duration_ms,
                                  diagnostics_factory, morphology_sha256,
                                  control_source_batches=None, paired_batches=False):
    """Route source events and restore trusted per-synapse geometry batchwise.

    Source archives and original diagnostics must have been authenticated by
    the caller. A supplied control must use the same configuration and time
    grid with stimulation disabled. Batches remain provisional until the end.
    """
    if (type(paired_batches) is not bool
            or (paired_batches and control_source_batches is not None)
            or not callable(diagnostics_factory) or not isinstance(morphology_sha256, dict)
            or not isinstance(expected_ids, list)
            or set(morphology_sha256) != set(expected_ids)):
        raise ValueError('Invalid source feedback identities')
    graph_hash = graph.provenance.get('manifest_sha256')
    if (not isinstance(graph_hash, str) or len(graph_hash) != 64
            or any(c not in '0123456789abcdef' for c in graph_hash)
            or any(not isinstance(value, str) or len(value) != 64
                   or any(c not in '0123456789abcdef' for c in value)
                   for value in morphology_sha256.values())):
        raise ValueError('Invalid source feedback digest')
    hashes = morphology_sha256.copy()
    merged_batches = []

    def edges():
        batches = (source_batches if paired_batches else
                   zip_longest(source_batches, control_source_batches)
                   if control_source_batches is not None else
                   ((batch, None) for batch in source_batches))
        for batch, control in batches:
            if not isinstance(batch, dict) or not batch:
                raise ValueError('Invalid archived source batch')
            if (paired_batches or control_source_batches is not None) and (
                    not isinstance(control, dict) or set(control) != set(batch)):
                raise ValueError('Control source batch identities do not match')
            originals = diagnostics_factory(tuple(batch))
            if not isinstance(originals, dict) or set(originals) != set(batch):
                raise ValueError('Incomplete source feedback diagnostics')
            merged = {}
            for body, source in batch.items():
                original = originals[body]
                if (not isinstance(original, dict) or original.get('body_id') != str(body)
                        or original.get('graph_sha256') != graph_hash
                        or original.get('morphology_sha256') != hashes.get(body)
                        or original.get('duration_ms') != duration_ms):
                    raise ValueError('Source feedback identity mismatch')
                merged[body] = merge_archived_source_events(
                    original, source, control=control[body] if control is not None else None)
            merged_batches.append(merged)
            yield {body: source['edge_events'] for body, source in batch.items()}

    try:
        for routed in iter_direct_feedback(graph, expected_ids, edges(), duration_ms=duration_ms):
            yield {'diagnostics': merged_batches.pop(), 'events': routed}
    finally:
        close = getattr(source_batches, 'close', None)
        if close is not None:
            close()
