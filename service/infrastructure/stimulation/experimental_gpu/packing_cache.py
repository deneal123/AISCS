"""Bounded, process-local cache of validated immutable GPU tree layouts."""

import hashlib
from collections import OrderedDict
from dataclasses import fields

import numpy as np

from .packing import pack_trees


class PackedTreeCache:
    """Reuse exact layouts; limit counts array bytes, excluding Python overhead."""

    def __init__(self, max_bytes):
        if type(max_bytes) is not int or max_bytes < 0:
            raise ValueError('Invalid packed tree cache limit')
        self.max_bytes = max_bytes
        self.bytes = 0
        self.entries = OrderedDict()

    def get_or_pack(self, trees):
        if not isinstance(trees, list) or not trees:
            raise ValueError('Invalid packed tree cache input')
        digest = hashlib.sha256()
        for tree in trees:
            if not isinstance(tree, tuple | list) or len(tree) != 3:
                raise ValueError('Invalid packed tree cache input')
            for item in tree:
                array = np.asarray(item)
                if array.ndim != 1 or array.dtype.kind not in 'iuf':
                    raise ValueError('Invalid packed tree cache input')
                digest.update(array.dtype.str.encode('ascii'))
                digest.update(len(array).to_bytes(8, 'little'))
                digest.update(np.ascontiguousarray(array).tobytes())
        key = digest.digest()
        if key in self.entries:
            value, size = self.entries.pop(key)
            self.entries[key] = (value, size)
            return value
        result = pack_trees(trees)
        size = sum(getattr(result, field.name).nbytes for field in fields(result))
        if size <= self.max_bytes:
            while self.bytes + size > self.max_bytes:
                _, (_, removed) = self.entries.popitem(last=False)
                self.bytes -= removed
            for field in fields(result):
                getattr(result, field.name).flags.writeable = False
            self.entries[key] = result, size
            self.bytes += size
        return result
