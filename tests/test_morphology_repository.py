import hashlib
import json

import pytest

from service.infrastructure.connectome.morphology_repository import BASE, read_skeleton


def test_read_requires_source_receipt_and_matching_content(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "receipts").mkdir()
    raw = b"1 0 0 0 0 1 -1\n2 0 10 0 0 1 1\n"
    (tmp_path / "raw" / "42.swc").write_bytes(raw)
    receipt = {"body_id": 42, "url": BASE + "42.swc", "sha256": hashlib.sha256(raw).hexdigest()}
    (tmp_path / "receipts" / "42.json").write_text(json.dumps(receipt))
    result = read_skeleton(42, [tmp_path])
    assert result["body_id"] == "42" and result["vertices"] == 2 and result["swc"] == raw.decode()
    (tmp_path / "raw" / "42.swc").write_bytes(raw + b"tampered")
    with pytest.raises(ValueError):
        read_skeleton(42, [tmp_path])
    with pytest.raises(FileNotFoundError):
        read_skeleton(43, [tmp_path])


@pytest.mark.parametrize('raw, valid', [
    (b'1 0 0 0 0 1 -1\n2 0 10 0 0 1 1\n', True),
    (b'1 0 0 0 0 1 -1\n2 0 10 0 0 1 3\n', False),
    (b'1 0 0 0 0 1 -1\n2 0 10 0 0 1 3\n3 0 20 0 0 1 2\n', False),
    (b'1 0 0 0 0 1 -1\n2 0 nan 0 0 1 1\n', False),
    (b'1 0 0 0 0 1 -1\n1 0 10 0 0 1 1\n', False),
])
def test_topology_only_uses_same_validation_and_receipt(tmp_path, raw, valid):
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'receipts').mkdir()
    (tmp_path / 'raw/42.swc').write_bytes(raw)
    receipt = {'body_id': 42, 'url': BASE + '42.swc', 'sha256': hashlib.sha256(raw).hexdigest()}
    (tmp_path / 'receipts/42.json').write_text(json.dumps(receipt))
    if valid:
        full = read_skeleton(42, [tmp_path])
        fast = read_skeleton(42, [tmp_path], topology_only=True)
        assert all(fast[key] == full[key] for key in fast)
        parsed = read_skeleton(42, [tmp_path], topology_only=True, include_validated_nodes=True)
        assert parsed['validated_nodes'][1][3] == pytest.approx(.008)
        assert all(parsed[key] == fast[key] for key in fast)
    else:
        for options in ({}, {'topology_only': True},
                        {'topology_only': True, 'include_validated_nodes': True}):
            with pytest.raises(ValueError, match='failed validation'):
                read_skeleton(42, [tmp_path], **options)
    (tmp_path / 'raw/42.swc').write_bytes(raw + b'tampered')
    with pytest.raises(ValueError, match='failed validation'):
        read_skeleton(42, [tmp_path], topology_only=True)
    with pytest.raises(ValueError, match='failed validation'):
        read_skeleton(42, [tmp_path], topology_only=True, include_validated_nodes=True)


@pytest.mark.parametrize('kwargs', [
    {'include_validated_nodes': True},
    {'topology_only': True, 'include_validated_nodes': True, 'expected_sha256': '0' * 64},
    {'topology_only': True, 'include_validated_nodes': 'true'},
])
def test_validated_node_request_rejects_unsafe_modes_before_read(tmp_path, kwargs):
    with pytest.raises(ValueError, match='Invalid validated node request'):
        read_skeleton(42, [tmp_path], **kwargs)


def test_audited_snapshot_read_still_checks_receipt_and_exact_digest(tmp_path, monkeypatch):
    (tmp_path / "raw").mkdir()
    (tmp_path / "receipts").mkdir()
    raw = b"1 0 0 0 0 1 -1\n2 0 10 0 0 1 1\n"
    digest = hashlib.sha256(raw).hexdigest()
    (tmp_path / "raw" / "42.swc").write_bytes(raw)
    receipt = {"body_id": 42, "url": BASE + "42.swc", "sha256": digest}
    path = tmp_path / "receipts" / "42.json"
    path.write_text(json.dumps(receipt))
    monkeypatch.setattr("service.infrastructure.connectome.morphology_repository.neurite_landmark",
                        lambda _: pytest.fail("audited snapshot must not reparse the morphology"))
    assert read_skeleton(42, [tmp_path], expected_sha256=digest)["swc"] == raw.decode()
    changed = raw + b"3 0 20 0 0 1 2\n"
    (tmp_path / "raw" / "42.swc").write_bytes(changed)
    receipt["sha256"] = hashlib.sha256(changed).hexdigest()
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="failed validation"):
        read_skeleton(42, [tmp_path], expected_sha256=digest)


def test_valid_copy_can_recover_from_corrupted_first_directory(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for directory in (first, second):
        (directory / "raw").mkdir(parents=True)
        (directory / "receipts").mkdir()
    raw = b"1 0 0 0 0 1 -1\n2 0 10 0 0 1 1\n"
    receipt = {"body_id": 42, "url": BASE + "42.swc", "sha256": hashlib.sha256(raw).hexdigest()}
    for directory in (first, second):
        (directory / "receipts" / "42.json").write_text(json.dumps(receipt))
    (first / "raw" / "42.swc").write_bytes(raw + b"damaged")
    (second / "raw" / "42.swc").write_bytes(raw)
    assert read_skeleton(42, [first, second])["sha256"] == receipt["sha256"]
    (second / "raw" / "42.swc").write_bytes(raw + b"damaged")
    with pytest.raises(ValueError):
        read_skeleton(42, [first, second])


@pytest.mark.parametrize("receipt", ["[]", "null", "42", '"not-an-object"'])
def test_receipt_with_wrong_json_type_is_reported_as_corruption(tmp_path, receipt):
    (tmp_path / "raw").mkdir()
    (tmp_path / "receipts").mkdir()
    (tmp_path / "raw" / "42.swc").write_text("1 0 0 0 0 1 -1\n")
    (tmp_path / "receipts" / "42.json").write_text(receipt)
    with pytest.raises(ValueError, match="failed validation"):
        read_skeleton(42, [tmp_path])


@pytest.mark.parametrize("body_id", [True, 0, -1, 2**63, "../42"])
def test_invalid_identity_is_rejected_before_access(tmp_path, body_id):
    with pytest.raises(ValueError, match="Invalid neuron ID"):
        read_skeleton(body_id, [tmp_path])
