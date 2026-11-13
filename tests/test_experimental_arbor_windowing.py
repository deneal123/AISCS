import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_arbor.windowing import run_windowed


class Simulation:
    def __init__(self):
        self.end = 0.
        self.cleared = 0
        self.pending = False

    def run(self, end, dt):
        assert not self.pending
        self.end, self.dt, self.pending = end, dt, True

    def samples(self, handle):
        return [(np.array([[self.end-self.dt, handle]], dtype=float), 'geometry')]

    def spikes(self):
        return np.array([(self.end,)], dtype=[('time', 'f8')])

    def clear_samplers(self):
        assert self.pending
        self.pending = False
        self.cleared += 1


def test_each_window_is_handed_off_before_samples_and_spikes_are_cleared():
    simulation = Simulation()
    observed = []

    def save(window):
        assert simulation.pending
        observed.append((window.start_ms, window.end_ms,
                         float(window.samples['v'][0][0][0, 1]), float(window.spikes['time'][0])))

    run_windowed(simulation, {'v': 7}, duration_ms=2.5, dt_ms=.5,
                 window_ms=1., ms_unit=1., on_window=save)
    assert observed == [(0., 1., 7., 1.), (1., 2., 7., 2.), (2., 2.5, 7., 2.5)]
    assert simulation.cleared == 3


def test_failed_handoff_leaves_the_buffer_intact():
    simulation = Simulation()

    def fail(_window):
        raise OSError('storage unavailable')

    with pytest.raises(OSError, match='storage unavailable'):
        run_windowed(simulation, {'v': 1}, duration_ms=2., dt_ms=.5,
                     window_ms=1., ms_unit=1., on_window=fail)
    assert simulation.pending and simulation.cleared == 0


def test_duplicate_samples_across_windows_are_rejected_before_clearing():
    simulation = Simulation()
    simulation.samples = lambda _handle: [(np.array([[.5, 1.]]), 'geometry')]
    with pytest.raises(ValueError, match='sample times'):
        run_windowed(simulation, {'v': 1}, duration_ms=2., dt_ms=.5,
                     window_ms=1., ms_unit=1., on_window=lambda _window: None)
    assert simulation.cleared == 1 and simulation.pending


def test_spikes_outside_current_window_are_rejected_before_clearing():
    simulation = Simulation()
    simulation.spikes = lambda: np.array([(2.,)], dtype=[('time', 'f8')])
    with pytest.raises(ValueError, match='spike buffer'):
        run_windowed(simulation, {'v': 1}, duration_ms=2., dt_ms=.5,
                     window_ms=1., ms_unit=1., on_window=lambda _window: None)
    assert simulation.pending and simulation.cleared == 0


@pytest.mark.parametrize('duration,dt,window', [
    (0., .1, 1.), (1., 0., 1.), (1., .3, .3), (1., .1, .25), (1., .1, float('nan')),
])
def test_nonfinite_or_unaligned_timesteps_are_rejected(duration, dt, window):
    with pytest.raises(ValueError):
        run_windowed(Simulation(), {'v': 1}, duration_ms=duration, dt_ms=dt,
                     window_ms=window, ms_unit=1., on_window=lambda _window: None)
