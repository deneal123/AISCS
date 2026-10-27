import numpy as np

FEATURES = ["rms_uv", "peak_to_peak_uv", "mean_square_uv2"]


def features(time_ms, signal_uv) -> np.ndarray:
    window = np.asarray(signal_uv)[np.asarray(time_ms) >= 20]
    return np.array([np.sqrt(np.mean(window**2)), np.ptp(window), np.mean(window**2)])
