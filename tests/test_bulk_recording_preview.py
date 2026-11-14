import numpy as np
import pytest

from service.application.population.bulk_recording_preview import bulk_recording_preview


def test_preview_keeps_actual_extrema_without_inventing_network_data():
    times = np.arange(10000) * .05
    signal = np.zeros(len(times))
    signal[123], signal[4567] = 10, -20
    result = bulk_recording_preview({'cells': 2, 'time_ms': times, 'neural_uv': signal,
        'replacement_receipts': [], 'interpretation': 'independent; no network feedback'},
        max_bins=20)
    assert max(result['neural_uv']) == 10 and min(result['neural_uv']) == -20
    assert result['shown_samples'] <= 80
    assert 'network_spikes_by_ms' not in result and 'total_uv' not in result
    assert all(t in times for t in result['time_ms'])


def test_preview_rejects_invalid_or_mislabelled_data():
    data = {'cells': 1, 'time_ms': [0., .05], 'neural_uv': [0., float('nan')],
            'replacement_receipts': [], 'interpretation': 'independent; no network feedback'}
    with pytest.raises(ValueError, match='samples'):
        bulk_recording_preview(data)
    with pytest.raises(ValueError, match='preview'):
        bulk_recording_preview({**data, 'interpretation': 'full CNS'})
