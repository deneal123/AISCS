import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.window_recording import (
    WindowedPointRecorder,
)
from service.infrastructure.stimulation.point_field import bipolar_potential_mv


def geometry(y):
    return {'starts_um': np.array([[0., y, 0.]]), 'ends_um': np.array([[2., y, 0.]]),
            'midpoints_um': np.array([[1., y, 0.]]),
            'endpoint_radii_um': np.array([[.1, .1]])}


def test_windows_accumulate_differential_and_require_complete_order():
    geometries = {1: geometry(0.), 2: geometry(2.)}
    e1, ref = [10., 0., 0.], [20., 0., 0.]
    recorder = WindowedPointRecorder(geometries, e1, ref, .3, clearance_um=1., samples=3)
    currents = {1: np.array([[1., 2., 3.]]), 2: np.array([[-1., 1., 2.]])}
    with pytest.raises(ValueError, match='Incomplete'):
        recorder.finish()
    for start, end in [(0, 1), (1, 3)]:
        recorder.accept(start, end, [{'id': body, 'membrane_current_na': values[:, start:end]}
                                     for body, values in currents.items()])
    expected = sum(1000 * bipolar_potential_mv(geometries[body]['midpoints_um'], e1, ref, 1., .3,
                   clearance_um=1.) @ values for body, values in currents.items())
    np.testing.assert_allclose(recorder.finish(), expected, rtol=1e-14, atol=1e-14)
    with pytest.raises(ValueError, match='order'):
        recorder.accept(1, 2, [])


def test_window_rejects_invalid_current_without_advancing():
    recorder = WindowedPointRecorder({1: geometry(0.)}, [10., 0., 0.], [20., 0., 0.],
                                     .3, clearance_um=1., samples=2)
    with pytest.raises(ValueError, match='currents'):
        recorder.accept(0, 1, [{'id': 1, 'membrane_current_na': [[float('nan')]]}])
    assert recorder.next_sample == 0


def test_batched_coefficients_match_individual_and_validate_every_cell():
    geometries = {1: geometry(0.), 2: geometry(2.), 3: geometry(4.)}
    e1, ref = [10., 0., 0.], [20., 0., 0.]
    recorder = WindowedPointRecorder(geometries, e1, ref, .3, clearance_um=1., samples=2)
    for body, g in geometries.items():
        expected = 1000 * bipolar_potential_mv(g['midpoints_um'], e1, ref, 1., .3,
                                                clearance_um=1.)
        np.testing.assert_array_equal(recorder.coefficients[body], expected)
    geometries[2] = geometry(0.)
    geometries[2]['starts_um'][0] = [9., 0., 0.]
    geometries[2]['ends_um'][0] = [11., 0., 0.]
    geometries[2]['midpoints_um'][0] = [10., 0., 0.]
    with pytest.raises(ValueError, match='intersects'):
        WindowedPointRecorder(geometries, e1, ref, .3, clearance_um=1., samples=2)
