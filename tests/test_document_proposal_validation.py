"""Workspace независимо сверяет версию и структуру до записи private proposal."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.projects import DocumentProjectError
from application.documents.proposals import store_proposal


def project():
    return SimpleNamespace(
        manifest=AsyncMock(),
        _run=AsyncMock(return_value=SimpleNamespace(stdout="stored")),
        authoring_state=AsyncMock(
            return_value={
                "authoring_version": 3,
                "draft_digest": "a" * 64,
                "draft": {
                    "blocks": [
                        {"block_id": "intro", "kind": "slide"},
                        {"block_id": "other", "kind": "slide"},
                    ]
                },
            }
        ),
    )


def proposal():
    return {
        "base_version": 3,
        "draft_digest": "a" * 64,
        "patch_version": 2,
        "replacements": [],
        "deletions": [],
        "moves": [],
        "selected_block_ids": ["intro"],
        "insertions": [{"after_id": "intro", "block": {"block_id": "new_cat", "kind": "slide"}}],
    }


@pytest.mark.asyncio
async def test_stores_one_valid_scoped_structural_proposal_only():
    projects, value = project(), proposal()
    item = SimpleNamespace(policy=SimpleNamespace(root="/workspace"))
    result = await store_proposal(projects, item, "documents/slides", value)
    assert len(result["proposal_id"]) == 32 and projects._run.await_count == 1
    saved = json.loads(projects._run.await_args.kwargs["stdin_payload"])
    assert saved["proposal"] == value and saved["path"] == "documents/slides"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["version", "digest", "selection", "id", "empty"])
async def test_invalid_or_stale_batch_never_reaches_storage(case):
    projects, value = project(), proposal()
    if case == "version":
        value["base_version"] = 1
    if case == "digest":
        value["draft_digest"] = "b" * 64
    if case == "selection":
        value["insertions"][0]["after_id"] = "other"
    if case == "id":
        value["insertions"][0]["block"]["block_id"] = "invented"
    if case == "empty":
        value["insertions"] = []
    with pytest.raises(DocumentProjectError):
        await store_proposal(projects, SimpleNamespace(), "documents/slides", value)
    projects._run.assert_not_awaited()
