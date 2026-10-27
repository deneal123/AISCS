"""One reproducible observation-noise path for generation and evaluation."""

import numpy as np


def add_noise(clean_signal, seed: int, noise_uv: float) -> np.ndarray:
    clean = np.asarray(clean_signal)
    rng = np.random.default_rng(np.random.SeedSequence([seed, 917]))
    return clean + rng.normal(0, noise_uv, clean.shape)
