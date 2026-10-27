import hashlib

import pytest

from service.services.chat.domain.ide.files import (
    MAX_READ_BYTES,
    IdeReadError,
    project_file,
    project_tree,
    validate_path,
)


def text_payload(content="hello"):
    return {
        "path": "main.py",
        "kind": "text",
        "size": len(content.encode()),
        "content": content,
        "digest": hashlib.sha256(content.encode()).hexdigest(),
        "truncated": False,
    }


@pytest.mark.parametrize(
    "path",
    [
        None,
        [],
        "",
        "/root",
        "../a",
        "a/../b",
        "a//b",
        "a\\b",
        ".git/config",
        "src/.gpthub-state",
        "node_modules/a",
        "x\n",
        "x" * 1025,
    ],
)
def test_paths_are_relative_visible_and_bounded(path):
    with pytest.raises(IdeReadError, match="ide_path_forbidden"):
        validate_path(path)


def test_public_projection_excludes_private_sidecar_fields():
    payload = text_payload()
    assert (
        project_file({**payload, "token": "PRIVATE", "workspace_id": "PRIVATE"}, "main.py")
        == payload
    )
    row = {"path": "src", "type": "dir", "size": 0, "incomplete": True}
    assert project_tree(
        {"entries": [{**row, "root": "PRIVATE"}], "truncated": True, "token": "PRIVATE"}, ""
    ) == {"entries": [row], "truncated": True}


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": []},
        {"kind": {}},
        {"size": True},
        {"size": -1},
        {"truncated": 1},
        {"path": "other"},
        {"digest": "0" * 64},
        {"content": None},
        {"content": "\ud800"},
        {"content": "a" * (MAX_READ_BYTES + 1)},
    ],
)
def test_malformed_file_cannot_be_an_edit_base(changes):
    with pytest.raises(IdeReadError):
        project_file({**text_payload(), **changes}, "main.py")


def test_truncated_text_has_no_full_content_digest():
    payload = {**text_payload(), "size": MAX_READ_BYTES + 1, "truncated": True, "digest": None}
    assert project_file(payload, "main.py")["digest"] is None
    with pytest.raises(IdeReadError):
        project_file({**payload, "digest": text_payload()["digest"]}, "main.py")


@pytest.mark.parametrize(
    "changes",
    [
        {"type": []},
        {"type": {}},
        {"size": True},
        {"size": -1},
        {"incomplete": 1},
        {"incomplete": True},
        {"path": "outside.py"},
        {"path": "src/../main.py"},
    ],
)
def test_invalid_tree_entry_is_not_forwarded(changes):
    row = {"path": "src/main.py", "type": "file", "size": 5, **changes}
    with pytest.raises(IdeReadError):
        project_tree({"entries": [row], "truncated": False}, "src")


@pytest.mark.parametrize(
    "entries", [[{"path": "a", "type": "file", "size": 0}] * 2, [None], ["a"] * 401]
)
def test_duplicate_oversized_or_malformed_trees_fail_closed(entries):
    with pytest.raises(IdeReadError):
        project_tree({"entries": entries, "truncated": False}, "")
