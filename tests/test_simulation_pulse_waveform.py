import pytest

from service.services.simulations.inputs.pulse_waveform import validate_projected_waveform


@pytest.mark.parametrize(('simulation', 'waveform'), [
    ({'duration_ms': 4, 'pulse_start_ms': .5, 'pulse_end_ms': 1.5,
      'rise_time_ms': 0, 'interphase_gap_ms': .5, 'pulse_shape': 'biphasic'},
     [.5, .5, -1., 0.]),
    ({'duration_ms': 4, 'pulse_start_ms': .25, 'pulse_end_ms': .75,
      'rise_time_ms': .25, 'interphase_gap_ms': 0, 'pulse_shape': 'monophasic',
      'pulse_count': 2, 'pulse_interval_ms': 1.5}, [.25, .125, .125, 0.]),
])
def test_independent_bin_integrals_and_tamper_detection(simulation, waveform):
    validate_projected_waveform(simulation, waveform)
    altered = waveform.copy()
    altered[1] += .01
    with pytest.raises(ValueError):
        validate_projected_waveform(simulation, altered)


def test_invalid_waveform_is_rejected():
    simulation = {'duration_ms': 4, 'pulse_start_ms': .5, 'pulse_end_ms': 1.5,
                  'rise_time_ms': 0, 'interphase_gap_ms': 0, 'pulse_shape': 'monophasic'}
    for waveform in ([0, .5, 0], [0, .5, float('nan'), 0], [True, .5, 0, 0]):
        with pytest.raises(ValueError):
            validate_projected_waveform(simulation, waveform)
