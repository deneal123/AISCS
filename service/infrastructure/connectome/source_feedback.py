"""Extract graph-model inputs suppressed at independently simulated sources.

These are LIF events with a model delay and predicted signs, not calibrated
synaptic conductances or a physical simulation of their effect on sources.
"""

from __future__ import annotations

import numpy as np


def suppressed_source_inputs(graph, source_ids, edge_events, network, *, duration_ms):
    if (not isinstance(source_ids, list) or not source_ids
            or len(set(source_ids)) != len(source_ids)
            or any(type(body) is not int or body <= 0 for body in source_ids)
            or type(duration_ms) is not int or duration_ms < 1
            or not isinstance(edge_events, list) or not isinstance(network, dict)):
        raise ValueError('Invalid source feedback input')
    source_positions = np.searchsorted(graph.ids, source_ids)
    if any(pos >= graph.size or int(graph.ids[pos]) != body
           for pos, body in zip(source_positions, source_ids, strict=True)):
        raise ValueError('Unknown source')
    positions = set(map(int, source_positions))
    selected_ids = set(source_ids)
    neurons = np.asarray(network.get('spike_neurons'))
    times = np.asarray(network.get('spike_times_ms'))
    if (neurons.ndim != 1 or neurons.dtype.kind not in 'iu' or times.shape != neurons.shape
            or not np.isfinite(times).all() or np.any(neurons < 0) or np.any(neurons >= graph.size)
            or np.any(times < 1) or np.any(times > duration_ms)
            or np.any(times != np.floor(times)) or np.isin(neurons, source_positions).any()):
        raise ValueError('Invalid graph events')
    incoming = []

    def append(pre, post, tick, count, kind):
        arrival = tick + 2
        incoming.append({'source_id': int(graph.ids[pre]), 'target_id': int(graph.ids[post]),
                         'emission_tick_ms': tick, 'delivery_tick_ms': arrival,
                         'synapse_count': count, 'predicted_sign': int(graph.signs[pre]),
                         'kind': kind, 'within_window': arrival <= duration_ms,
                         'affects_replay': arrival < duration_ms})
        if len(incoming) > 1_000_000:
            raise ValueError('Source feedback exceeds event limit')

    for event in edge_events:
        if not isinstance(event, dict) or set(event) != {'source_id', 'target_id', 'tick', 'count'}:
            raise ValueError('Invalid source edge event')
        if any(type(event[key]) is not int for key in event):
            raise ValueError('Invalid source edge event')
        if event['target_id'] not in selected_ids:
            continue
        pre = int(np.searchsorted(graph.ids, event['source_id']))
        post = int(np.searchsorted(graph.ids, event['target_id']))
        if (pre >= graph.size or int(graph.ids[pre]) != event['source_id']
                or event['source_id'] not in selected_ids
                or not 1 <= event['tick'] <= duration_ms or event['count'] <= 0):
            raise ValueError('Invalid source edge event')
        candidates = np.flatnonzero(graph.posts[graph.ptr[pre]:graph.ptr[pre + 1]] == post)
        if (len(candidates) != 1
                or event['count'] > int(graph.counts[graph.ptr[pre] + candidates[0]])):
            raise ValueError('Source edge is not registered')
        append(pre, post, event['tick'], event['count'], 'physical-source-edge')

    for pre, tick in zip(neurons, times, strict=True):
        pre = int(pre)
        for edge in range(int(graph.ptr[pre]), int(graph.ptr[pre + 1])):
            post = int(graph.posts[edge])
            if post in positions:
                append(pre, post, int(tick), int(graph.counts[edge]), 'lif-network-spike')
    incoming.sort(key=lambda item: (item['delivery_tick_ms'], item['source_id'],
                                    item['target_id'], item['kind']))
    return {'events': incoming, 'delivery_delay_ms': 2,
            'graph_sha256': graph.provenance.get('manifest_sha256'),
            'interpretation': 'suppressed LIF-model inputs; no physical feedback applied'}
