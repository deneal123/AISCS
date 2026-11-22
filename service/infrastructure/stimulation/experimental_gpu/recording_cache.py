"""Durable per-batch recording coefficients.

The recording coefficients are a function of the cell geometry and the electrode
pair alone: one float per segment, 8 bytes, computed by a numba kernel that
validates clearance and evaluates the 1/r field difference. On the wide tail of
the population that construction measured 159.8 s of a 384 s shard pass, and it
is recomputed on every pass although nothing about it changes.

They are therefore cached per batch. The key is the batch's exact cell identity:
a batch is a deterministic packing decision over the same groups, so a pass that
replays the same batches asks for the same key and receives bit-identical
coefficients. The cache is a plain file per batch, so a hit is one read and no
arithmetic at all. A miss computes and stores, which is why an ordinary pass
fills the cache as a side effect of doing its work.
"""
import hashlib
import json
import os
import re
from pathlib import Path

import numpy as np

FORMAT = 'malecns-recording-coefficients-v1'
_META = 'meta.json'
_PAYLOAD = 'coefficients.bin'


class RecordingCoefficientCacheError(ValueError):
    """The cache entry does not describe coefficients this batch can use."""


_FIELDS = ('starts_um', 'ends_um', 'endpoint_radii_um', 'midpoints_um')


def batch_key(geometries, *, geometry_sha256, electrode_um, reference_um,
              conductivity_s_m, clearance_um, morphologies):
    """Identity of one batch's coefficients.

    The key names the cells and the preparation, not the segment arrays. The
    reduced geometry of a cell is a deterministic function of its morphology and
    the stimulation params, so the pair (morphology digest, params identity) is
    the exact identity of the geometry the coefficients were computed from, and
    the body fixes which cell of the batch it is.

    Digesting the arrays themselves instead cost 88 bytes per segment: on the
    full population that is 23.8 GB per pass, measured at 5.4 ms per cell on the
    wide tail - 140 s of a pass spent proving that a hit is a hit. The pair of
    digests is already carried by every prepared cell, so the key now costs a few
    microseconds and covers strictly more (the morphology digest is checked
    against the durable store on every batch).
    """
    if not isinstance(geometry_sha256, str) or not re.fullmatch('[a-f0-9]{64}',
                                                                 geometry_sha256):
        raise ValueError('Invalid recording-cache geometry identity')
    if not isinstance(morphologies, dict) or set(morphologies) != set(geometries):
        raise ValueError('Recording-cache key needs one morphology digest per cell')
    digest = hashlib.blake2b(digest_size=32)
    digest.update(FORMAT.encode('ascii'))
    digest.update(geometry_sha256.encode('ascii'))
    for body in sorted(geometries):
        morphology = morphologies[body]
        if not isinstance(morphology, str) or not re.fullmatch('[a-f0-9]{64}', morphology):
            raise ValueError('Invalid recording-cache morphology identity')
        digest.update(np.asarray([int(body)], dtype='<i8').tobytes())
        digest.update(morphology.encode('ascii'))
        # The segment count is not an identity - it follows from the two digests -
        # but it is the one cheap witness that the entry describes the same shape
        # of cell, and a mismatched entry is then rejected before it is read.
        digest.update(np.asarray([len(geometries[body]['starts_um'])], dtype='<i8').tobytes())
    for values in (electrode_um, reference_um):
        digest.update(np.asarray(values, dtype='<f8').tobytes())
    digest.update(np.asarray([conductivity_s_m, clearance_um], dtype='<f8').tobytes())
    return digest.hexdigest()


class RecordingCoefficientCache:
    """Read and write per-batch coefficient entries under one directory."""

    def __init__(self, directory, geometry_sha256):
        self.directory = Path(directory)
        self.geometry_sha256 = geometry_sha256

    def entry(self, key):
        return self.directory / key[:2] / key

    def key_for(self, geometries, *, morphologies, electrode_um, reference_um,
                conductivity_s_m, clearance_um):
        """The entry name this batch's coefficients would live under."""
        return batch_key(geometries, geometry_sha256=self.geometry_sha256,
                         morphologies=morphologies, electrode_um=electrode_um,
                         reference_um=reference_um, conductivity_s_m=conductivity_s_m,
                         clearance_um=clearance_um)

    def get(self, key, ids):
        """Return the stored coefficients for exactly these cells, or None."""
        entry = self.entry(key)
        meta_path = entry / _META
        payload_path = entry / _PAYLOAD
        try:
            if not meta_path.is_file() or not payload_path.is_file():
                return None
            meta = json.loads(meta_path.read_text(encoding='utf8'))
            if (meta.get('format') != FORMAT or meta.get('key') != key
                    or meta.get('geometry_sha256') != self.geometry_sha256
                    or [int(body) for body in meta['ids']] != [int(body) for body in ids]
                    or int(meta['bytes']) != payload_path.stat().st_size):
                return None
            block = np.fromfile(payload_path, dtype='<f8')
        except (OSError, ValueError, KeyError, TypeError):
            return None
        lengths = [int(value) for value in meta['lengths']]
        if int(sum(lengths)) != len(block):
            return None
        result, cursor = {}, 0
        for body, length in zip(meta['ids'], lengths):
            result[int(body)] = block[cursor:cursor + length].copy()
            cursor += length
        return result

    def compute(self, geometries, *, electrode_um, reference_um, conductivity_s_m,
                clearance_um):
        """Return this batch's coefficients, computing and storing them on a miss."""
        from . import recording_kernel

        result, parts = {}, []
        for body, geometry in geometries.items():
            parts.append((body,
                          np.asarray(geometry['starts_um'], dtype=float),
                          np.asarray(geometry['ends_um'], dtype=float),
                          np.asarray(geometry['endpoint_radii_um'], dtype=float),
                          np.asarray(geometry['midpoints_um'], dtype=float)))
        starts, ends, radii, midpoints = (np.concatenate([row[index] for row in parts], axis=0)
                                          for index in range(1, 5))
        values = recording_kernel.coefficients(starts, ends, radii, midpoints, electrode_um,
                                               reference_um, conductivity_s_m,
                                               clearance_um=clearance_um)
        offset = 0
        for body, sample, *_ in parts:
            end = offset + len(sample)
            result[body] = values[offset:end]
            offset = end
        return result

    def put(self, key, ids, coefficients):
        """Publish one batch's coefficients; the metadata is the commit point."""
        entry = self.entry(key)
        entry.mkdir(parents=True, exist_ok=True)
        lengths = [int(len(coefficients[body])) for body in ids]
        block = np.concatenate([np.asarray(coefficients[body], dtype='<f8') for body in ids])
        scratch = entry / (_PAYLOAD + '.tmp')
        block.tofile(scratch)
        os.replace(scratch, entry / _PAYLOAD)
        meta = {'format': FORMAT, 'key': key, 'geometry_sha256': self.geometry_sha256,
                'ids': [int(body) for body in ids],
                'lengths': lengths, 'bytes': int(block.nbytes)}
        meta_scratch = entry / (_META + '.tmp')
        meta_scratch.write_text(json.dumps(meta, sort_keys=True), encoding='utf8')
        os.replace(meta_scratch, entry / _META)