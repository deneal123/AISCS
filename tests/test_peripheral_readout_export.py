"""Central segment membership alone must not create peripheral nerve activity."""

from scripts.export_peripheral_readout import peripheral_group


def test_only_annotated_peripheral_populations_are_selected():
    row = {
        "superclass": "vnc_sensory",
        "entryNerve": "ProLN",
        "exitNerve": None,
        "rootSide": "L",
        "somaSide": None,
        "somaNeuromere": None,
    }
    assert peripheral_group(row)[:2] == ("front_left", "sensory")
    assert peripheral_group({**row, "superclass": "vnc_intrinsic", "somaNeuromere": "A1"}) is None
    assert peripheral_group({**row, "entryNerve": "AbN4"})[:2] == ("abdomen", "sensory")
    assert peripheral_group({**row, "rootSide": "unknown"}) is None
    assert peripheral_group({**row, "rootSide": None, "somaSide": "L"}) is None
