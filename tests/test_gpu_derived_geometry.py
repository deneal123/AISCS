import hashlib

import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.derived_geometry import (
    prepare_contracted_cell,
)
from service.infrastructure.stimulation.experimental_gpu.fast_cable import Params


def test_derived_geometry_preparation_uses_derived_identity_and_keeps_branches():
    raw = (b'1 2 0 0 0 20 -1\n2 2 0 0 0 20 1\n'
           b'3 2 1000 0 0 20 2\n4 2 0 1000 0 20 2\n')
    params = Params(source_um=(100., 100., 100.), return_um=(200., 100., 100.),
                    current_na=100., conductivity_s_m=.3, clearance_um=.1)
    source = hashlib.sha256(raw).hexdigest()
    cell, receipt = prepare_contracted_cell(raw, source_sha256=source, body_id=42,
                                             parent_id=1, child_id=2, params=params)
    assert cell['id'] == 42 and cell['morphology_sha256'] == receipt['derived_sha256']
    assert receipt['source_sha256'] == source and receipt['reassigned_child_ids'] == [3, 4]
    assert set(cell['geometry']['edge_node_ids']) == {3, 4}
    assert np.isfinite(cell['field_current_na']).all()
    with pytest.raises(ValueError, match='identity'):
        prepare_contracted_cell(raw, source_sha256='a' * 64, body_id=42,
                                parent_id=1, child_id=2, params=params)
