"""Fingerprint numerical inputs to an independent GPU population replay."""

import hashlib
import json
from dataclasses import asdict, is_dataclass

import numpy as np


def numerical_inputs_sha256(*, params, stimulus, time_ms, rate_table, expected_ids,
                            electrode_um, reference_um, conductivity_s_m, clearance_um):
    """Hash explicit numerical inputs; this is not complete run provenance."""
    if (not is_dataclass(params) or isinstance(params, type)
            or not isinstance(expected_ids, list) or not expected_ids
            or any(type(body) is not int or body <= 0 for body in expected_ids)
            or len(set(expected_ids)) != len(expected_ids)):
        raise ValueError('Invalid numerical identity inputs')
    metadata = {'params': asdict(params), 'expected_ids': expected_ids,
                'electrode_um': list(electrode_um), 'reference_um': list(reference_um),
                'conductivity_s_m': conductivity_s_m, 'clearance_um': clearance_um}
    digest = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(',', ':'),
                                       allow_nan=False).encode('utf-8'))
    for values in (stimulus, time_ms, rate_table):
        array = np.ascontiguousarray(values, dtype='<f8')
        if not np.isfinite(array).all():
            raise ValueError('Invalid numerical identity array')
        digest.update(json.dumps(array.shape, separators=(',', ':')).encode('ascii'))
        digest.update(array.tobytes())
    return digest.hexdigest()
