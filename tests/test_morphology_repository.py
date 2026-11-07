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
