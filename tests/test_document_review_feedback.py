"""PDF-отказ даёт проверяемую причину, не раскрывая содержимое или полномочия."""

import json
from unittest.mock import AsyncMock

import pytest

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.tools import document_proposal_tool


def document_target():
    return {
        "content": json.dumps(
            {
                "title": "Документ",
                "version": 3,
                "blocks": [{"block_id": "slide_1", "kind": "slide", "text": "PRIVATE_DOCUMENT"}],
            }
        ),
        "path": "documents/slides",
        "draft_digest": "a" * 64,
        "expected_revision": "r1",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,reason,status,retryable",
    [
        ("json", "invalid_patch", "invalid", True),
        ("bool", "invalid_patch", "invalid", True),
        ("version", "stale_base_version", "invalid", True),
        ("unknown", "unknown_block_id", "invalid", True),
        ("duplicate", "invalid_patch", "invalid", True),
        ("selection", "outside_selection", "failed", False),
        ("missing_draft", "draft_unavailable", "failed", False),
    ],
)
async def test_rejected_review_never_writes_or_charges_and_explains_correction(
    monkeypatch, case, reason, status, retryable
):
    target = document_target()
    arguments = {"base_version": 3, "replacements": [{"block_id": "slide_1", "kind": "slide"}]}
    if case == "bool":
        arguments["base_version"] = True
    if case == "version":
        arguments["base_version"] = 1
    if case == "unknown":
        arguments["replacements"][0]["block_id"] = "missing_block"
    if case == "duplicate":
        arguments["replacements"] *= 2
    if case == "selection":
        target["block_ids"] = ["slide_2"]
    if case == "missing_draft":
        target["content"] = "PRIVATE_DOCUMENT_INVALID_JSON"
    remote = AsyncMock()
    monkeypatch.setattr(document_proposal_tool, "call", remote)
    reference = {"document_context": target, "token": "PRIVATE_CAPABILITY"}
    with use_run_execution(PrivateRunResources(workspace_ref=reference)) as execution:
        outcome = await document_proposal_tool.propose_document_patch(
            None, "not json" if case == "json" else json.dumps(arguments)
        )
        feedback = json.loads(outcome.text)
        assert outcome.status == status and outcome.retryable is retryable
        assert not outcome.succeeded and not outcome.charged
        assert feedback["error_code"] == reason
        assert any("а" <= char <= "я" for char in feedback["message"])
        assert "PRIVATE" not in outcome.text
        assert not execution.policy.values.get("document_proposal")
    remote.assert_not_awaited()
