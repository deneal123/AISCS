import numpy as np
import pytest

from service.domain.pulse_train import pulse_train
from service.infrastructure.stimulation.experimental_gpu.recording_adapter import (
    attach_stimulation,
    attach_windowed_artifact,
)
from service.infrastructure.stimulation.experimental_gpu.waveform import kernel_midpoint_samples
from service.infrastructure.stimulation.point_field import bipolar_potential_mv
from service.infrastructure.stimulation.virtual_current import junction_currents


@pytest.fixture
def inputs():
    config = {'pulse_start_ms': .025, 'pulse_end_ms': .075, 'rise_time_ms': 0.,
              'interphase_gap_ms': 0., 'pulse_shape': 'monophasic',
              'source_um': [0., 0., 0.], 'return_um': [20., 0., 0.],
              'current_na': 1., 'conductivity_s_m': .3, 'clearance_um': .1}
    times, levels = pulse_train(start_ms=.025, end_ms=.075, rise_ms=0., interphase_gap_ms=0.,
                                shape='monophasic', duration_ms=.1, count=1, interval_ms=None)
    midpoint = kernel_midpoint_samples(times, levels, dt_ms=.025, steps=4)
    arrays = {'time_ms': np.arange(5) * .025, 'midpoints_um': np.array([[10., 2., 0.]])}
    junctions = [[(0, 1.)], [(0, 1.)]]
    field = bipolar_potential_mv(arrays['midpoints_um'], config['source_um'], config['return_um'],
                                 1., .3, clearance_um=.1)
    return {'arrays': arrays, 'config': config, 'events': [], 'stimulus_midpoint': midpoint,
            'field_current_na': junction_currents(field, junctions), 'junctions': junctions}


def test_attaches_checked_field_and_pulse(inputs):
    result = attach_stimulation(**inputs)
    assert result['stimulation_parameters'].shape == (14,)
    assert result['synaptic_events_sha256'].shape == (32,)
    assert result['stimulus_fraction'].shape == (5,)


def test_rejects_mismatched_waveform(inputs):
    inputs['stimulus_midpoint'][1] = .25
    with pytest.raises(ValueError, match='stimulus'):
        attach_stimulation(**inputs)


def test_rejects_mismatched_field_current(inputs):
    inputs['field_current_na'][0] = 1.
    with pytest.raises(ValueError, match='field'):
        attach_stimulation(**inputs)


def test_windowed_artifact_is_added_once_and_validates_field(inputs):
    cell = {'id': 1, 'events': [], 'field_current_na': inputs['field_current_na'],
            'geometry': {'midpoints_um': inputs['arrays']['midpoints_um'],
                         'junctions': inputs['junctions']}}
    replay = {'time_ms': inputs['arrays']['time_ms'], 'neural_uv': np.ones(5),
              'sources': {1: {}}}
    result = attach_windowed_artifact(replay, [cell], config=inputs['config'],
        stimulus_midpoint=inputs['stimulus_midpoint'], electrode_um=[5., 5., 0.],
        reference_um=[15., 3., 0.])
    np.testing.assert_allclose(result['total_uv'],
                               result['neural_uv'] + result['stimulus_artifact_uv'])
    cell['field_current_na'] = [1.]
    with pytest.raises(ValueError, match='field'):
        attach_windowed_artifact(replay, [cell], config=inputs['config'],
            stimulus_midpoint=inputs['stimulus_midpoint'], electrode_um=[5., 5., 0.],
            reference_um=[15., 3., 0.])


def test_windowed_artifact_checks_every_cell_and_waveform(inputs):
    good = {'id': 1, 'events': [], 'field_current_na': inputs['field_current_na'],
            'geometry': {'midpoints_um': inputs['arrays']['midpoints_um'],
                         'junctions': inputs['junctions']}}
    bad = {**good, 'id': 2, 'field_current_na': [1.]}
    replay = {'time_ms': inputs['arrays']['time_ms'], 'neural_uv': np.ones(5),
              'sources': {1: {}, 2: {}}}
    with pytest.raises(ValueError, match='field'):
        attach_windowed_artifact(replay, [good, bad], config=inputs['config'],
            stimulus_midpoint=inputs['stimulus_midpoint'], electrode_um=[5., 5., 0.],
            reference_um=[15., 3., 0.])
    wrong_waveform = inputs['stimulus_midpoint'].copy()
    wrong_waveform[1] = .25
    with pytest.raises(ValueError, match='stimulus'):
        attach_windowed_artifact(replay, [good, {**good, 'id': 2}], config=inputs['config'],
            stimulus_midpoint=wrong_waveform, electrode_um=[5., 5., 0.],
            reference_um=[15., 3., 0.])
