import base64
import hashlib
import hmac
import json

import pytest
from application.recovery import (
    RestoreSnapshot,
    mint_manifest,
    parse_manifest,
    restore_receipt,
)
from domain.policy import WorkspacePolicy

SECRET = "restore-signature-fixture-not-a-deployment-secret"


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("WORKSPACE_OWNER_SECRET", SECRET)


@pytest.mark.parametrize(
    "digest,size",
    [
        ("A" * 64, 10),
        ("a" * 63, 10),
        ("a" * 65, 10),
        (None, 10),
        ("a" * 64, 0),
        ("a" * 64, True),
        ("a" * 64, 2**31),
        ("a" * 64, 1.0),
    ],
)
def test_invalid_snapshot_identity_is_not_a_restore_intent(digest, size):
    with pytest.raises(ValueError):
        RestoreSnapshot(digest, size)


def test_normal_v2_manifest_remains_unchanged_and_cannot_mint_a_restore_receipt():
    token = mint_manifest("repo", "owner", 1000, WorkspacePolicy())
    assert parse_manifest(token).restore_snapshot is None
    raw = base64.urlsafe_b64decode(token.partition(".")[0] + "==")
    assert json.loads(raw)["v"] == 2 and "restore" not in json.loads(raw)
    with pytest.raises(ValueError):
        restore_receipt(token)


def test_restore_identity_and_receipt_bind_owner_allocation_policy_deadline_and_source():
    snapshot = RestoreSnapshot("a" * 64, 100)
    values = [
        ("repo", "owner", 1000, WorkspacePolicy(), snapshot),
        ("other", "owner", 1000, WorkspacePolicy(), snapshot),
        ("repo", "other", 1000, WorkspacePolicy(), snapshot),
        ("repo", "owner", 1001, WorkspacePolicy(), snapshot),
        ("repo", "owner", 1000, WorkspacePolicy(quota_bytes=123), snapshot),
        ("repo", "owner", 1000, WorkspacePolicy(), RestoreSnapshot("b" * 64, 100)),
        ("repo", "owner", 1000, WorkspacePolicy(), RestoreSnapshot("a" * 64, 101)),
    ]
    tokens = [mint_manifest(*row[:4], restore_snapshot=row[4]) for row in values]
    assert len({restore_receipt(token) for token in tokens}) == len(values)
    for token, row in zip(tokens, values, strict=True):
        assert parse_manifest(token).restore_snapshot == row[4]
        assert restore_receipt(token) not in token
        assert row[4].sha256 not in repr(parse_manifest(token))
    assert restore_receipt(tokens[0]) == restore_receipt(tokens[0])


@pytest.mark.parametrize("change", ["digest", "version", "size", "extra"])
def test_tampered_restore_label_never_becomes_ready(change):
    token = mint_manifest(
        "repo", "owner", 1000, WorkspacePolicy(), restore_snapshot=RestoreSnapshot("a" * 64, 100)
    )
    encoded, _, signature = token.partition(".")
    value = json.loads(base64.urlsafe_b64decode(encoded + "=="))
    if change == "digest":
        value["restore"]["sha256"] = "b" * 64
    elif change == "version":
        value["v"] = 2
    elif change == "size":
        value["restore"]["size"] = 101
    else:
        value["extra"] = True
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    altered = base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + signature
    assert parse_manifest(altered) is None
    with pytest.raises(ValueError):
        restore_receipt(altered)


@pytest.mark.parametrize(
    "restore",
    [{}, {"sha256": "a" * 64, "size": True}, {"sha256": "a" * 64, "size": 100, "extra": 1}],
)
def test_even_authenticated_but_invalid_restore_fields_are_rejected(restore):
    token = mint_manifest(
        "repo", "owner", 1000, WorkspacePolicy(), restore_snapshot=RestoreSnapshot("a" * 64, 100)
    )
    value = json.loads(base64.urlsafe_b64decode(token.partition(".")[0] + "=="))
    value["restore"] = restore
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(
        SECRET.encode(), b"gpthub-workspace-manifest-v3|" + raw, hashlib.sha256
    ).hexdigest()
    assert (
        parse_manifest(base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + signature) is None
    )
