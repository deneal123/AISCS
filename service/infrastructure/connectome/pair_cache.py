"""Bounded, run-local reuse of indexed pairs already checked during mapping."""

from __future__ import annotations

from copy import deepcopy

from service.infrastructure.connectome.synapse_index import SynapseBatchIndex


class VerifiedSynapsePairs:
    """Cache index observations, never physiology or morphology conclusions."""

    def __init__(self, index, *, max_rows=100_000):
        if not isinstance(index, SynapseBatchIndex) or type(max_rows) is not int or max_rows < 0:
            raise ValueError('Invalid verified pair cache')
        self._index = index
        self._source_md5 = index.manifest['source_md5']
        self._source_fingerprint = index.source_fingerprint
        self._index_fingerprints = index.index_fingerprints
        self._max_rows = max_rows
        self._row_count = 0
        self._pairs = {}
        self.verify(index, self._source_md5)

    def verify(self, index, expected_source_md5):
        if (index is not self._index or expected_source_md5 != self._source_md5
                or index.manifest.get('source_md5') != self._source_md5
                or index.source_fingerprint != self._source_fingerprint
                or index.index_fingerprints != self._index_fingerprints):
            raise ValueError('Pair cache index identity mismatch')
        index.assert_unchanged()

    def remember(self, index, source, target, rows, source_md5):
        self.verify(index, source_md5)
        if (type(source) is not int or source <= 0 or type(target) is not int or target <= 0
                or source == target or not isinstance(rows, list) or not rows
                or any(not isinstance(row, dict) or row.get('body_pre') != source
                       or row.get('body_post') != target for row in rows)):
            raise ValueError('Invalid verified pair observations')
        key = (source, target)
        previous = self._pairs.get(key)
        if previous is not None:
            if previous != rows:
                raise ValueError('Conflicting verified pair observations')
            return
        if self._row_count + len(rows) <= self._max_rows:
            self._pairs[key] = deepcopy(rows)
            self._row_count += len(rows)

    def get(self, source, target):
        rows = self._pairs.get((source, target))
        return None if rows is None else deepcopy(rows)
