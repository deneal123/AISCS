"""Index one verified immutable graph event stream for repeated cell replays.

This is an indexing optimization only. It neither predicts excitation nor
changes the original event times, graph, or replay model.
"""

from __future__ import annotations

import math

import numpy as np

from service.infrastructure.stimulation.synaptic_replay import _read_verified_spike_arrays


class VerifiedSpikeIndex:
    """Validate the source once and index event times by registered graph ID."""

    def __init__(self, binary, description, expected_sha256, graph_ids, graph_manifest_sha256):
        indices, times = _read_verified_spike_arrays(
            binary, description, expected_sha256, graph_ids, graph_manifest_sha256
        )
        self._ids = np.array(graph_ids, copy=True)
        order = np.argsort(indices, kind="stable")
        self._times = np.array(times[order], copy=True)
        counts = np.bincount(indices, minlength=len(self._ids))
        self._offsets = np.concatenate(([0], np.cumsum(counts, dtype=np.int64)))
        self._indices = indices
        self._source_times = times
        self._ids.flags.writeable = False
        self._times.flags.writeable = False
        self._offsets.flags.writeable = False
        self.source_sha256 = expected_sha256
        self.graph_manifest_sha256 = graph_manifest_sha256
        self.duration_ms = float(description["duration_ms"])

    def select(self, partner_ids):
        if (not isinstance(partner_ids, list | tuple)
                or any(type(value) is not int or value <= 0 for value in partner_ids)
                or len(set(partner_ids)) != len(partner_ids)):
            raise ValueError("Invalid replay partner IDs")
        positions = np.searchsorted(self._ids, partner_ids)
        if any(pos >= len(self._ids) or int(self._ids[pos]) != body
               for pos, body in zip(positions, partner_ids, strict=True)):
            raise ValueError("Replay partner missing from graph")
        return {
            str(body): self._times[self._offsets[pos]:self._offsets[pos + 1]].astype(float).tolist()
            for pos, body in zip(positions, partner_ids, strict=True)
        }

    def active_before(self, duration_ms, delay_ms):
        if (isinstance(duration_ms, bool) or not isinstance(duration_ms, int | float)
                or not math.isfinite(duration_ms) or duration_ms <= 0
                or isinstance(delay_ms, bool) or not isinstance(delay_ms, int | float)
                or not math.isfinite(delay_ms) or delay_ms < 0 or duration_ms > self.duration_ms):
            raise ValueError("Invalid replay time window")
        return {int(self._ids[index]) for index in
                self._indices[self._source_times.astype(float) + delay_ms < duration_ms]}
