"""Signal-only summaries for a fixed 200 ms, 40 kHz synthetic recording."""

import numpy as np

FEATURES = [
    "pre_rms_uv",
    "active_rms_uv",
    "post_rms_uv",
    "active_peak_to_peak_uv",
    "active_mean_abs_difference_uv",
    "active_power_0_500hz_fraction",
    "active_early_to_late_rms_ratio",
]
VERSION = "male-cns-signal-summaries-v1"


def features(time_ms, signal_uv) -> np.ndarray:
    time, signal = np.asarray(time_ms), np.asarray(signal_uv)
    if (
        time.ndim != 1
        or signal.shape != time.shape
        or len(time) != 8001
        or not np.isfinite(time).all()
        or not np.isfinite(signal).all()
        or abs(time[0]) > 1e-7
        or abs(time[-1] - 200) > 1e-6
        or not np.allclose(np.diff(time), 0.025, atol=1e-7, rtol=0)
    ):
        raise ValueError("Recognition requires a finite 200 ms recording at 0.025 ms")

    def rms(values):
        return float(np.sqrt(np.mean(values**2)))

    pre = signal[(time >= 10) & (time < 25)]
    active = signal[(time >= 25) & (time < 175)]
    post = signal[time >= 175]
    power = np.abs(np.fft.rfft(active - active.mean())) ** 2
    frequencies = np.fft.rfftfreq(len(active), d=0.000025)
    low = float(power[(frequencies > 0) & (frequencies <= 500)].sum() / max(power.sum(), 1e-18))
    early, late = signal[(time >= 25) & (time < 100)], signal[(time >= 100) & (time < 175)]
    return np.array(
        [
            rms(pre),
            rms(active),
            rms(post),
            np.ptp(active),
            np.mean(np.abs(np.diff(active))),
            low,
            rms(early) / max(rms(late), 1e-9),
        ]
    )
