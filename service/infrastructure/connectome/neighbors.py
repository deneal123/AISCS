"""Bounded adjacency from the exact registered graph."""

from functools import lru_cache

import numpy as np

from service.infrastructure.connectome.dataset import load_registered_graph
from service.settings import connectome_directory


@lru_cache(maxsize=1)
def registered_graph():
    return load_registered_graph(connectome_directory())


def outgoing(graph, body_id: int, offset: int, limit: int) -> dict:
    index = int(np.searchsorted(graph.ids, body_id))
    if index >= len(graph.ids) or int(graph.ids[index]) != body_id:
        raise KeyError("Neuron is not in the registered graph")
    first, last = int(graph.ptr[index]), int(graph.ptr[index + 1])
    begin, end = min(first + offset, last), min(first + offset + limit, last)
    sign = int(graph.signs[index])
    return {
        "dataset_id": graph.provenance["dataset_id"],
        "manifest_sha256": graph.provenance["manifest_sha256"],
        "source_id": str(body_id),
        "offset": offset,
        "total": last - first,
        "next_offset": end - first if end < last else None,
        "items": [
            {
                "target_id": str(int(graph.ids[int(graph.posts[i])])),
                "synapse_count": int(graph.counts[i]),
                "model_sign": sign,
            }
            for i in range(begin, end)
        ],
        "limitations": "Sign is derived from predicted transmitter, without receptor context.",
    }


def incoming(graph, body_id: int, offset: int, limit: int) -> dict:
    index = int(np.searchsorted(graph.ids, body_id))
    if index >= len(graph.ids) or int(graph.ids[index]) != body_id:
        raise KeyError("Neuron is not in the registered graph")
    total, selected = 0, []
    for start in range(0, len(graph.posts), 1_000_000):
        block = graph.posts[start : start + 1_000_000]
        matches = np.flatnonzero(block == index) + start
        first, last = max(0, offset - total), min(len(matches), offset + limit - total)
        if first < last:
            selected.extend(int(edge) for edge in matches[first:last])
        total += len(matches)
    source_indices = np.searchsorted(graph.ptr, selected, side="right") - 1
    return {
        "dataset_id": graph.provenance["dataset_id"],
        "manifest_sha256": graph.provenance["manifest_sha256"],
        "target_id": str(body_id),
        "offset": offset,
        "total": total,
        "next_offset": offset + len(selected) if offset + len(selected) < total else None,
        "items": [
            {
                "source_id": str(int(graph.ids[int(source)])),
                "synapse_count": int(graph.counts[edge]),
                "model_sign": int(graph.signs[int(source)]),
            }
            for edge, source in zip(selected, source_indices, strict=True)
        ],
        "limitations": "Sign is derived from predicted transmitter, without receptor context.",
    }


def incoming_edge_indices_many(graph, body_ids, *, block_size=1_000_000):
    """Locate incoming CSR edge indices for several targets in one graph scan.

    Indices are candidates into the registered graph, not synapse coordinates.
    Results preserve source CSR order, matching ``incoming``. Callers should
    bound the target set and account for the returned edge-array memory.
    """
    if (not isinstance(body_ids, (list, tuple)) or not body_ids
            or any(type(body) is not int or body <= 0 for body in body_ids)
            or len(set(body_ids)) != len(body_ids)
            or type(block_size) is not int or block_size < 1):
        raise ValueError('Invalid incoming target batch')
    positions = np.searchsorted(graph.ids, body_ids)
    if any(pos >= len(graph.ids) or int(graph.ids[pos]) != body
           for pos, body in zip(positions, body_ids, strict=True)):
        raise KeyError('Neuron is not in the registered graph')
    selected = np.zeros(len(graph.ids), dtype=np.bool_)
    selected[positions] = True
    chunks = {body: [] for body in body_ids}
    by_position = {int(pos): body for pos, body in zip(positions, body_ids, strict=True)}
    for start in range(0, len(graph.posts), block_size):
        posts = graph.posts[start:start + block_size]
        matches = np.flatnonzero(selected[posts])
        if not len(matches):
            continue
        targets = posts[matches]
        for target in np.unique(targets):
            chunks[by_position[int(target)]].append(matches[targets == target] + start)
    return {body: (np.concatenate(parts) if parts else np.empty(0, dtype=np.int64))
            for body, parts in chunks.items()}
