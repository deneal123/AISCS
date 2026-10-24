"""Настоящий subprocess проверяет атомарную публикацию, не проект пользователя."""

import json
import os
import subprocess
import sys

import pytest
from application.documents.proposal_storage import STORE_SCRIPT
from domain.documents.document_review import review_proposal_id


def test_identity_is_canonical_and_revision_path_selection_sensitive():
    proposal = {"base_version": 3, "replacements": [], "selected_block_ids": ["intro"]}
    identity = review_proposal_id("documents/cats", proposal)
    assert len(identity) == 32
    assert identity == review_proposal_id("documents/cats", dict(reversed(list(proposal.items()))))
    assert identity != review_proposal_id("documents/other", proposal)
    assert identity != review_proposal_id("documents/cats", {**proposal, "base_version": 4})
    assert identity != review_proposal_id("documents/cats", {**proposal, "selected_block_ids": []})


linux_runtime = pytest.mark.skipif(
    not hasattr(os, "O_NOFOLLOW"), reason="Скрипт исполняется в Linux runtime workspace"
)


def store(root, identity, payload):
    return subprocess.run(
        [sys.executable, "-c", STORE_SCRIPT, str(root), identity],
        input=payload,
        capture_output=True,
        timeout=10,
        check=False,
    )


@linux_runtime
def test_atomic_duplicate_reuses_one_file_and_rejects_changed_bytes(tmp_path):
    root, identity, payload = tmp_path / "proposals", "a" * 32, b'{"safe":true}'
    first = store(root, identity, payload)
    assert first.returncode == 0 and first.stdout.strip() == b"stored"
    second = store(root, identity, payload)
    assert second.returncode == 0 and second.stdout.strip() == b"reused"
    conflict = store(root, identity, b'{"changed":true}')
    assert conflict.returncode != 0
    assert (root / (identity + ".json")).read_bytes() == payload
    assert len(list(root.iterdir())) == 1


@linux_runtime
def test_existing_proposal_can_be_read_at_retention_cap(tmp_path):
    root = tmp_path / "proposals"
    root.mkdir()
    for index in range(64):
        (root / (f"{index:032x}" + ".json")).write_bytes(b"{}")
    assert store(root, "0" * 32, b"{}").stdout.strip() == b"reused"
    assert store(root, "f" * 32, b"{}").returncode != 0
    assert len(list(root.iterdir())) == 64


@linux_runtime
def test_symlink_target_is_never_followed(tmp_path):
    root, identity = tmp_path / "proposals", "a" * 32
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text(json.dumps({"private": True}))
    (root / (identity + ".json")).symlink_to(outside)
    assert store(root, identity, b"{}").returncode != 0
    assert json.loads(outside.read_text()) == {"private": True}
