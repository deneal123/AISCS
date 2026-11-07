import hashlib
import json
import math

import pytest

from scripts.audit_swc_geometry import describe
from service.infrastructure.connectome.morphology_repository import BASE


def test_describe_uses_source_identity_and_correct_frustum_units(tmp_path):
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'receipts').mkdir()
    raw = b'1 1 0 0 0 62.5 -1\n2 3 1250 0 0 62.5 1\n'
    (tmp_path / 'raw' / '42.swc').write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    (tmp_path / 'receipts' / '42.json').write_text(json.dumps({
        'body_id': 42, 'url': BASE + '42.swc', 'sha256': digest,
    }))
    result = describe(42, [tmp_path])
    assert result['source_sha256'] == digest and result['components'] == 1
    assert result['cable_length_um'] == pytest.approx(10)
    assert result['frustum_lateral_area_um2'] == pytest.approx(10 * math.pi)
    (tmp_path / 'raw' / '42.swc').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='validation'):
        describe(42, [tmp_path])
