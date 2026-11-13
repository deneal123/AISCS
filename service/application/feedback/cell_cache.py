"""Bounded, run-local cache for exactly identical physical cell inputs."""

import copy
import hashlib
import json
import sys
from collections import OrderedDict

import numpy as np


def _size(value):
    if isinstance(value, np.ndarray):
        # Deep copies own their buffers, including arrays that started as views.
        return max(sys.getsizeof(value), value.nbytes + 128)
    if isinstance(value, dict):
        return sys.getsizeof(value) + sum(_size(key) + _size(item) for key, item in value.items())
    if isinstance(value, tuple | list):
        return sys.getsizeof(value) + sum(_size(item) for item in value)
    return sys.getsizeof(value)


class CellSolutionCache:
    """Never share between runs: caller fixes source files and software version."""

    def __init__(self, max_bytes, *, policy='lru'):
        if type(max_bytes) is not int or max_bytes < 0 or policy not in ('lru', 'stable'):
            raise ValueError('Invalid cache size')
        self.max_bytes = max_bytes
        self.policy = policy
        self.entries = OrderedDict()
        self.groups = {}
        self.bytes = 0

    @staticmethod
    def key(body, morphology_hash, simulation, events, overrides):
        payload = {'body': body, 'morphology': morphology_hash, 'simulation': simulation,
                   'events': events, 'overrides': overrides}
        canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def get(self, key):
        if key not in self.entries:
            return None
        value, size = self.entries.pop(key)
        self.entries[key] = (value, size)
        return copy.deepcopy(value)

    def put(self, key, value, *, group=None):
        if self.policy == 'stable' and (type(group) is not int or group <= 0):
            raise ValueError('Stable cache requires a cell ID')
        size = _size(value)
        if size > self.max_bytes:
            return
        if self.policy == 'stable' and group in self.groups and self.groups[group] != key:
            old_key = self.groups.pop(group)
            _, old_size = self.entries.pop(old_key)
            self.bytes -= old_size
        if key in self.entries:
            _, old_size = self.entries.pop(key)
            self.bytes -= old_size
            if self.policy == 'stable' and self.groups.get(group) == key:
                self.groups.pop(group)
        if self.policy == 'stable' and self.bytes + size > self.max_bytes:
            return
        while self.bytes + size > self.max_bytes:
            _, (_, old_size) = self.entries.popitem(last=False)
            self.bytes -= old_size
        self.entries[key] = (copy.deepcopy(value), size)
        if self.policy == 'stable':
            self.groups[group] = key
        self.bytes += size
