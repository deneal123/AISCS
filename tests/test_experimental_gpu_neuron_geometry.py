import numpy as np
import pytest

pytest.importorskip('neuron')

from neuron import h  # noqa: E402

from service.infrastructure.stimulation.experimental_gpu.neuron_geometry import (  # noqa: E402
    prepare_neuron_geometry,
)
from service.infrastructure.stimulation.virtual_current import adaptive_junctions  # noqa: E402


def test_geometry_cleanup_after_success_and_rejection():
    nodes = {1: ([0., 0., 0.], 1.), 2: ([10., 0., 0.], 1.)}
    result = prepare_neuron_geometry([(2, 1)], nodes, {2: 3},
                                     axial_resistivity=100., capacitance=1.)
    assert len(result['area']) == 3
    assert result['edge_node_ids'].tolist() == [2, 2, 2]
    assert not list(h.allsec())
    with pytest.raises(ValueError):
        prepare_neuron_geometry([(2, 1)], nodes, {2: 2},
                                axial_resistivity=100., capacitance=1.)
    assert not list(h.allsec())


def test_existing_sections_are_not_deleted():
    section = h.Section(name='existing')
    try:
        with pytest.raises(RuntimeError, match='isolated'):
            prepare_neuron_geometry([(2, 1)], {1: ([0, 0, 0], 1), 2: ([1, 0, 0], 1)},
                                    {2: 1}, axial_resistivity=100., capacitance=1.)
        assert list(h.allsec()) == [section]
    finally:
        h.delete_section(sec=section)


def test_refined_geometry_preserves_order_and_interpolates_taper():
    nodes = {1: ([0., 0., 0.], 1.), 2: ([9., 0., 0.], 4.),
             3: ([9., 6., 0.], 1.)}
    result = prepare_neuron_geometry([(2, 1), (3, 2)], nodes, {2: 3, 3: 1},
                                     axial_resistivity=100., capacitance=1.)
    assert result['grid'] == [(2, 0, 3), (2, 1, 3), (2, 2, 3), (3, 0, 1)]
    np.testing.assert_allclose(result['starts_um'], [[0, 0, 0], [3, 0, 0],
                                                      [6, 0, 0], [9, 0, 0]])
    np.testing.assert_allclose(result['ends_um'], [[3, 0, 0], [6, 0, 0],
                                                    [9, 0, 0], [9, 6, 0]])
    np.testing.assert_allclose(result['endpoint_radii_um'], [[1, 2], [2, 3],
                                                              [3, 4], [4, 1]])


def test_precomputed_resistances_preserve_junctions():
    section = h.Section(name='junction_test')
    try:
        section.L = 12
        section.diam = 2
        section.nseg = 3
        h.define_shape()
        segments = list(section)
        edges, counts, sections = [(2, 1)], {2: 3}, {2: section}
        reference = adaptive_junctions(edges, counts, sections, segments)
        reused = adaptive_junctions(edges, counts, sections, segments,
                                   segment_resistances=[segment.ri() for segment in segments],
                                   child_resistances=[section(1).ri()])
        assert reused == reference
        with pytest.raises(ValueError, match='precomputed'):
            adaptive_junctions(edges, counts, sections, segments, segment_resistances=[])
    finally:
        h.delete_section(sec=section)


@pytest.mark.parametrize('point,radius', [([0, 0, 0], 1), ([1, 0], 1),
                                        ([1, float('nan'), 0], 1), ([1, 0, 0], 0)])
def test_invalid_vectorized_geometry_is_rejected(point, radius):
    nodes = {1: ([0., 0., 0.], 1.), 2: (point, radius)}
    with pytest.raises(ValueError, match='coordinates or radii'):
        prepare_neuron_geometry([(2, 1)], nodes, {2: 1},
                                axial_resistivity=100., capacitance=1.)
    assert not list(h.allsec())
