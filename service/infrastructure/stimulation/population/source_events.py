"""Encode unique source-cell/tick markers for candidate segment crossings.

Markers mean at least one indexed candidate segment crossed the chosen threshold.
They do not establish a whole-cell spike or propagation along every graph edge.
"""

from __future__ import annotations

import re
import struct

import numpy as np

HEADER = struct.Struct('<4sIII32s32s')


def encode_population_source_events(physical, graph, *, duration_ms, configuration_sha256):
    graph_hash = graph.provenance.get('manifest_sha256')
    if (not isinstance(physical, dict) or physical.get('graph_sha256') != graph_hash
            or any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value)
                   for value in (graph_hash, configuration_sha256))
            or type(duration_ms) is not int or not 1 <= duration_ms <= 1000
            or not 1 <= graph.size < 2**32):
        raise ValueError('Invalid source event identity')
    ids, rows = physical.get('source_ids'), physical.get('candidate_events_by_source')
    if (not isinstance(ids, list) or not ids or len(ids) > 256
            or any(type(body) is not int or body <= 0 for body in ids)
            or len(set(ids)) != len(ids) or not isinstance(rows, dict) or set(rows) != set(ids)):
        raise ValueError('Invalid source event population')
    positions = np.searchsorted(graph.ids, ids)
    if any(position >= graph.size or int(graph.ids[position]) != body
           for position, body in zip(positions, ids, strict=True)):
        raise ValueError('Source event neuron is not in graph')
    events = set()
    for body, position in zip(ids, positions, strict=True):
        if not isinstance(rows[body], list):
            raise ValueError('Invalid source candidates')
        for row in rows[body]:
            ticks = row.get('stimulated_ticks_ms') if isinstance(row, dict) else None
            if (not isinstance(ticks, list)
                    or any(type(tick) is not int or not 1 <= tick <= duration_ms for tick in ticks)
                    or any(a >= b for a, b in zip(ticks, ticks[1:], strict=False))):
                raise ValueError('Invalid source candidate ticks')
            events.update((tick, int(position)) for tick in ticks)
    ordered = sorted(events)
    if len(ordered) > len(ids) * duration_ms:
        raise ValueError('Source event count exceeds bound')
    times = np.asarray([tick for tick, _ in ordered], dtype='<u4')
    indices = np.asarray([position for _, position in ordered], dtype='<u4')
    return (HEADER.pack(b'SRC1', graph.size, duration_ms, len(ordered),
                        bytes.fromhex(graph_hash), bytes.fromhex(configuration_sha256))
            + indices.tobytes() + times.tobytes())
