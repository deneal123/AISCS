import struct

import pytest

from scripts.export_sensory_arbors import input_region, packed_swc


def test_packed_swc_preserves_source_coordinates_and_parent_identity():
    raw = b"20 3 100 200 300 1 10\n10 1 90 200 300 2 -1\n30 3 110 200 300 1 20\n"
    binary, receipt = packed_swc(raw)
    rows = list(struct.iter_unpack("<fffi", binary))
    assert len(rows) == receipt["vertices"] == 3
    assert [row[3] for row in rows] == [-1, 0, 1]
    assert rows[0][:3] == pytest.approx([0.72, 1.6, 2.4])
    assert rows[2][:3] == pytest.approx([0.88, 1.6, 2.4])
    with pytest.raises(ValueError, match="Cyclic"):
        packed_swc(b"1 3 0 0 0 1 2\n2 3 1 1 1 1 1\n3 1 2 2 2 1 -1\n")


def test_sensory_population_requires_a_registered_nerve_and_side():
    cell = {
        "superclass": "vnc_sensory",
        "class": "mechanosensory_tactile",
        "entryNerve": "ProLN",
        "rootSide": "L",
        "somaSide": "R",
    }
    assert input_region(cell) == "front_left"
    assert input_region({**cell, "rootSide": None}) == "front_right"
    assert input_region({**cell, "entryNerve": "AbN"}) is None
    assert input_region({**cell, "entryNerve": None}) is None
    assert input_region({**cell, "entryNerve": "PDMN", "subclass": "notum"}) == "notum"
    assert input_region({**cell, "entryNerve": "PDMN", "subclass": "mechanosensory bristle"}) is None
