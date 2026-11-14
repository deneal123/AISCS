import hashlib

import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.derived_geometry import (
    prepare_contracted_cell,
)
from service.infrastructure.stimulation.experimental_gpu.fast_cable import CACHE_RECORD, Params
from service.infrastructure.stimulation.experimental_gpu.fast_prepare import (
    FastPrepareError,
    iter_prepared_chunks,
)


def test_explicit_replacement_preserves_identity_and_requires_receipt(tmp_path):
    raw = (b'1 2 0 0 0 20 -1\n2 2 0 0 0 20 1\n'
           b'3 2 1000 0 0 20 2\n4 2 0 1000 0 20 2\n')
    digest = hashlib.sha256(raw).hexdigest()
    rows = np.array([(0, 0, 0, .16, -1, 1), (0, 0, 0, .16, 0, 2),
                     (8, 0, 0, .16, 1, 3), (0, 8, 0, .16, 1, 4)], dtype=CACHE_RECORD)
    data = rows.tobytes()
    (tmp_path / 'chunk-000000.bin').write_bytes(data)
    descriptor = {'name': 'chunk-000000.bin', 'format': 'malecns-packed-geometry-chunk-v1',
                  'vertices': 4, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                  'neurons': [{'body_id': '42', 'source_sha256': digest, 'offset': 0, 'count': 4}]}
    metadata = {'directory': tmp_path, 'neurons': 1, 'vertices': 4, 'chunks': [descriptor]}
    params = Params(source_um=(100., 100., 100.), return_um=(200., 100., 100.),
                    current_na=100., conductivity_s_m=.3, clearance_um=.1)
    def factory(body, code, source):
        assert body == 42 and code != 0 and source == digest
        return prepare_contracted_cell(raw, source_sha256=source, body_id=body,
                                       parent_id=1, child_id=2, params=params)
    options = dict(audited_sources={42: digest}, params=params, workers=1)
    with pytest.raises(FastPrepareError, match='Rejected morphology'):
        list(iter_prepared_chunks(metadata, **options))
    receipts = []
    result = list(iter_prepared_chunks(metadata, **options, replacement_factory=factory,
                                        on_replacement=lambda *args: receipts.append(args)))
    assert result[0][0] == [42] and result[0][1][0]['id'] == 42
    assert receipts[0][2]['source_sha256'] == digest
    assert result[0][1][0]['morphology_sha256'] == receipts[0][2]['derived_sha256']
    with pytest.raises(FastPrepareError, match='provenance callback'):
        list(iter_prepared_chunks(metadata, **options, replacement_factory=factory))
