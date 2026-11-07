import numpy as np
import pytest

from service.infrastructure.stimulation.acquisition import acquire_channel


def channel(time, neural, artifact, stimulus, **kwargs):
    return acquire_channel(time, neural, artifact, stimulus, low_hz=100, high_hz=1000, **kwargs)


def test_filter_band_and_linear_decomposition():
    time = np.arange(10000) * 0.1
    seconds = time / 1000
    passband = np.sin(2 * np.pi * 500 * seconds)
    stopband = np.sin(2 * np.pi * 20 * seconds)
    result = channel(time, passband, stopband, np.zeros_like(time))
    np.testing.assert_allclose(
        result['filtered_total_uv'], result['filtered_neural_uv'] + result['filtered_artifact_uv'],
        atol=1e-12,
    )
    assert np.sqrt(np.mean(result['filtered_neural_uv'][5000:] ** 2)) > 0.65
    assert np.sqrt(np.mean(result['filtered_artifact_uv'][5000:] ** 2)) < 0.04
    assert result['valid_samples'].all()
    assert not result['saturated_samples'].any()


def test_blanking_covers_interphase_gap_and_recovery():
    time = np.arange(100) * 0.1
    stimulus = np.zeros_like(time)
    stimulus[20:30] = 1
    stimulus[35:40] = -1
    result = channel(time, time * 0, time * 0, stimulus, recovery_ms=0.5)
    assert result['valid_samples'][:20].all()
    assert not result['valid_samples'][20:45].any()
    assert result['valid_samples'][45:].all()


def test_clipping_is_before_filter_and_not_decomposed():
    time = np.arange(1000) * 0.1
    neural = np.sin(time)
    artifact = np.full_like(time, 5)
    result = channel(time, neural, artifact, np.zeros_like(time), clip_uv=2)
    assert result['saturated_samples'].all()
    assert not result['valid_samples'].any()
    assert 'filtered_neural_uv' not in result
    assert 'filtered_artifact_uv' not in result
    np.testing.assert_allclose(result['raw_total_uv'], neural + artifact)
    unclipped_equivalent = channel(
        time, np.full_like(time, 2), np.zeros_like(time), np.zeros_like(time)
    )
    np.testing.assert_allclose(
        result['filtered_total_uv'], unclipped_equivalent['filtered_total_uv']
    )


def test_filter_memory_makes_post_clipping_samples_invalid():
    time = np.arange(1000) * 0.1
    neural = np.zeros_like(time)
    neural[300] = 3
    result = channel(time, neural, np.zeros_like(time), np.zeros_like(time), clip_uv=2)
    assert result['valid_samples'][:300].all()
    assert not result['valid_samples'][300:].any()
    assert result['saturated_samples'].sum() == 1


@pytest.mark.parametrize(
    'change', ['irregular', 'nan', 'nyquist', 'negative_recovery', 'boolean', 'overflow']
)
def test_invalid_inputs_are_rejected(change):
    time = np.arange(100, dtype=float) * 0.1
    neural = np.zeros_like(time)
    artifact = np.zeros_like(time)
    stimulus = np.zeros_like(time)
    settings = {'low_hz': 100, 'high_hz': 1000}
    if change == 'irregular':
        time[5] += 0.01
    elif change == 'nan':
        stimulus[0] = np.nan
    elif change == 'nyquist':
        settings['high_hz'] = 5000
    elif change == 'negative_recovery':
        settings['recovery_ms'] = -1
    elif change == 'boolean':
        settings['low_hz'] = True
    else:
        neural[:] = artifact[:] = 1e308
    with pytest.raises(ValueError):
        acquire_channel(time, neural, artifact, stimulus, **settings)
