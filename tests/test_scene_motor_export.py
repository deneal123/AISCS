"""The display readout must not silently use intrinsic cells as motor neurons."""

import pytest

from scripts.export_scene_motor import motor_population


def test_motor_selection_requires_nerve_neuromere_and_laterality():
    row = {"superclass": "vnc_motor", "exitNerve": "ProLN", "somaSide": "L", "somaNeuromere": "T1"}
    assert motor_population(row) == "front_left"
    assert motor_population({**row, "superclass": "vnc_intrinsic"}) is None
    assert motor_population({**row, "exitNerve": "AbN1"}) is None
    for patch in ({"somaSide": None}, {"somaNeuromere": "T2"}):
        with pytest.raises(ValueError):
            motor_population({**row, **patch})
