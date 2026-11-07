import numpy as np
import pytest

from service.infrastructure.stimulation.virtual_current import junction_currents


def test_junction_elimination_matches_independent_kirchhoff_calculation():
    field = np.array([-.4, .7, -.15])
    resistance = np.array([63.66, 16.98, 12.73])
    junctions = [[(0, 20.)], list(enumerate(resistance.tolist())), [(1, 8.)], [(2, 9.)]]
    actual = junction_currents(field, junctions)
    conductance = 1 / resistance
    junction_voltage = sum(field[i] * conductance[i] for i in range(3)) / sum(conductance)
    expected = np.array([(junction_voltage - field[i]) / resistance[i] for i in range(3)])
    np.testing.assert_allclose(actual, expected, rtol=1e-14, atol=1e-14)
    assert abs(actual.sum()) < 1e-14
    np.testing.assert_allclose(junction_currents(np.ones(3) * 50, junctions), 0, atol=1e-14)


def test_chain_current_is_equal_and_opposite_and_handles_disconnected_terminals():
    junctions = [[(0, 2.)], [(0, 3.), (1, 7.)], [(1, 4.)], [(2, 5.)], [(2, 6.)]]
    np.testing.assert_allclose(junction_currents([3., 7., 100.], junctions), [.4, -.4, 0.])


@pytest.mark.parametrize('field,junctions', [
    ([1], [[(0, 1.)]]),
    ([1], [[(0, 1.), (0, 1.)]]),
    ([1], [[(0, 0.)], [(0, 1.)]]),
    ([float('nan')], [[(0, 1.)], [(0, 1.)]]),
    ([1], [[(True, 1.)], [(0, 1.)]]),
])
def test_invalid_geometry_is_rejected(field, junctions):
    with pytest.raises(ValueError):
        junction_currents(field, junctions)
