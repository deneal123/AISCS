import json

import pytest

from scripts.audit_grouped_window_probe import audit


def test_grouped_audit_restores_order_and_rejects_duplicates(tmp_path):
    baseline, grouped = tmp_path / 'baseline.jsonl', tmp_path / 'grouped.jsonl'
    rows = [{'id': 1, 'max_abs_uv': 1., 'clamped': False},
            {'id': 2, 'max_abs_uv': 2., 'clamped': False}]
    baseline.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    out = [{'index': 1, **rows[1]}, {'index': 0, **rows[0]}]
    grouped.write_text(''.join(json.dumps(row) + '\n' for row in out))
    assert audit(baseline, grouped)['complete'] is True
    grouped.write_text(json.dumps(out[0]) + '\n' + json.dumps(out[0]) + '\n')
    with pytest.raises(ValueError, match='mismatched'):
        audit(baseline, grouped)
