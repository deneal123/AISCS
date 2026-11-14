import hashlib

import pytest

from service.infrastructure.stimulation.zero_edge_transform import contract_zero_edge


def test_explicit_zero_edge_preserves_branches_and_records_hashes():
    raw = (b'# source\n1 2 0 0 0 1 -1\n2 2 0 0 0 2 1\n'
           b'3 2 1 0 0 1 2\n4 2 0 1 0 1 2\n')
    digest = hashlib.sha256(raw).hexdigest()
    derived, receipt = contract_zero_edge(raw, expected_sha256=digest, parent_id=1, child_id=2)
    assert derived == b'# source\n1 2 0 0 0 1 -1\n3 2 1 0 0 1 1\n4 2 0 1 0 1 1\n'
    assert receipt['source_sha256'] == digest
    assert receipt['derived_sha256'] == hashlib.sha256(derived).hexdigest()
    assert receipt['reassigned_child_ids'] == [3, 4]


def test_rejects_wrong_digest_nonzero_edge_and_cycles():
    raw = b'1 2 0 0 0 1 -1\n2 2 1 0 0 1 1\n'
    with pytest.raises(ValueError, match='identity'):
        contract_zero_edge(raw, expected_sha256='a' * 64, parent_id=1, child_id=2)
    with pytest.raises(ValueError, match='zero-length'):
        contract_zero_edge(raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
                           parent_id=1, child_id=2)
    cyclic = b'1 2 0 0 0 1 2\n2 2 0 0 0 1 1\n'
    with pytest.raises(ValueError, match='cycle'):
        contract_zero_edge(cyclic, expected_sha256=hashlib.sha256(cyclic).hexdigest(),
                           parent_id=1, child_id=2)


def test_rejects_additional_degenerate_edges_without_silent_repair():
    raw = (b'1 2 0 0 0 1 -1\n2 2 0 0 0 1 1\n'
           b'3 2 0 0 0 1 2\n4 2 1 0 0 1 3\n')
    with pytest.raises(ValueError, match='other zero-length'):
        contract_zero_edge(raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
                           parent_id=1, child_id=2)
