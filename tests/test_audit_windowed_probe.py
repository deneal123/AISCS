import json

import numpy as np
import pytest

from scripts.audit_windowed_probe import audit, padded_segments


def test_audit_distinguishes_partial_and_tampered_results(tmp_path):
    ids = tmp_path / 'ids.npy'
    np.save(ids, np.array([1, 2]))
    receipts = tmp_path / 'receipts'
    receipts.mkdir()
    for body in (1, 2):
        (receipts / f'{body}.json').write_text(json.dumps({'sha256': str(body)}))
    results = tmp_path / 'results.jsonl'
    row = {'id': 1, 'sha256': '1', 'segments': 4, 'prepare_seconds': 1.,
           'seconds': 2., 'peak_rss_kib': 10, 'max_abs_uv': .1, 'clamped': False}
    results.write_text(json.dumps(row) + '\n')
    partial = audit(results, ids, receipts, limit=2)
    assert partial['complete'] is False
    assert partial['sum_prepare_seconds'] == 1.
    assert partial['sum_cell_seconds'] == 2.
    row['sha256'] = 'wrong'
    results.write_text(json.dumps(row) + '\n')
    with pytest.raises(ValueError, match='cell 1'):
        audit(results, ids, receipts, limit=2)


def test_padding_estimate_accounts_for_incomplete_batch():
    assert padded_segments([1, 3, 2, 4, 7], 4) == 23
    assert padded_segments([], 4) == 0
