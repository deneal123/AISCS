"""GET-проекция v1/v2 не пишет и не переносит предложение на новую базу."""

from copy import deepcopy

import pytest
from fastapi import HTTPException

from service.services.chat.application.documents.proposals import proposal_draft


def draft():
    return {
        "title": "Котики",
        "version": 1,
        "blocks": [
            {"block_id": "intro", "kind": "slide", "text": "Первый"},
            {"block_id": "other", "kind": "slide", "text": "Не менять"},
        ],
    }


def test_v2_projection_keeps_metadata_and_existing_blocks():
    before = draft()
    original = deepcopy(before)
    proposal = {
        "patch_version": 2,
        "replacements": [],
        "deletions": [],
        "moves": [],
        "insertions": [{"after_id": "intro", "block": {"block_id": "new_cat", "kind": "slide"}}],
        "selected_block_ids": ["intro"],
    }
    result = proposal_draft(before, proposal, stale=False)
    assert result["version"] == before["version"] and result["title"] == before["title"]
    assert [block["block_id"] for block in result["blocks"]] == ["intro", "new_cat", "other"]
    assert before == original


def test_stale_proposal_is_not_rebased_or_claimed_unchanged():
    before = draft()
    assert proposal_draft(before, {"replacements": [{"block_id": "missing"}]}, stale=True) is before


def test_invalid_structure_is_bounded_error_not_partial_projection():
    before = draft()
    with pytest.raises(HTTPException) as raised:
        proposal_draft(before, {"patch_version": 2, "replacements": []}, stale=False)
    assert raised.value.status_code == 422 and raised.value.detail == "document_proposal_invalid"
    assert before == draft()
