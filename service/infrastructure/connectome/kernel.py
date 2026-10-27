# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Artem X and Fly Arena contributors
# Exact advance/signed_weights functions from Fly Arena at 12f48c702ed170b5bdc4643afa7ce65e952b353d.
# See LICENSE-Fly-Arena.txt and provenance.json.

import numpy as np
from numba import njit


@njit(cache=True)
def advance(ptr, posts, weights, voltage, current, refractory, queue, clock, drive, steps, silenced=None):
    n = len(voltage)
    counts = np.zeros(n, dtype=np.int32)
    membrane_decay = np.exp(-1.0 / 20.0)
    current_decay = np.exp(-1.0 / 5.0)
    for tick in range(steps):
        slot = (clock + tick) % 3
        delivery = (clock + tick + 2) % 3
        # Process deliveries and all cells before propagating current spikes.
        for i in range(n):
            current[i] = current[i] * current_decay + queue[slot, i]
            queue[slot, i] = 0.0
            if silenced is not None and silenced[i]:
                voltage[i] = 0.0
                current[i] = 0.0
                refractory[i] = 0
                continue
            if refractory[i] > 0:
                refractory[i] -= 1
                voltage[i] = 0.0
                continue
            voltage[i] = max(-30.0, membrane_decay * voltage[i] + (1 - membrane_decay) * (drive[i] + current[i]))
            if voltage[i] >= 7.0:
                voltage[i] = 0.0
                refractory[i] = 2
                counts[i] += 1
                for edge in range(ptr[i], ptr[i + 1]):
                    queue[delivery, posts[edge]] += weights[edge]
    return counts


@njit(cache=True)
def signed_weights(ptr, counts, signs, gain):
    weights = np.empty(len(counts), dtype=np.float32)
    for source in range(len(signs)):
        for edge in range(ptr[source], ptr[source + 1]):
            weights[edge] = float(counts[edge]) * signs[source] * gain
    return weights
