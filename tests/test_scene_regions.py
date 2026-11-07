from types import SimpleNamespace

import numpy as np

from service.infrastructure.connectome.scene import REGIONS, scene_arrays


def test_ascending_neuron_soma_is_classified_by_neuromere_without_moving_it():
    graph = SimpleNamespace(
        size=3, ids=np.array([16897, 16898, 16899]),
        annotations={"somaLocation": [[48813, 55636, 130970]] * 3,
                     "tosomaLocation": [None] * 3,
                     "superclass": ["ascending_neuron", "cb_intrinsic", "vnc_sensory"],
                     "somaNeuromere": ["T3", None, "T1"],
                     "entryNerve": [None, None, "ProLN"], "exitNerve": [None] * 3,
                     "rootSide": [None, None, "L"], "somaSide": [None] * 3},
        ptr=np.array([0, 0, 0, 0]), posts=np.array([], dtype=int),
        counts=np.array([], dtype=int), signs=np.array([1, 1, 1]),
    )
    arrays, _ = scene_arrays(graph, np.zeros(3, dtype=int))
    assert [REGIONS[index] for index in arrays["regions"]] == ["thorax", "brain", "front_left"]
    np.testing.assert_allclose(arrays["raw_um"], [[48813 * .008, 55636 * .008, 130970 * .008]] * 3)
    np.testing.assert_array_equal(arrays["positions_mm"][0], arrays["positions_mm"][1])
