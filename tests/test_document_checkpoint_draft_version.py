"""A completed repaired draft must not regress to version one on resume."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.documents import normalize_brief
from service.domain.documents.authoring import execution as runtime
from service.domain.documents.authoring.checkpoint import restore_authoring_checkpoint
from service.domain.documents.semantic.outline import parse_document_outline


def _payload(version):
    result = {
        "schema_version": 1,
        "stage": "complete",
        "draft_version": version,
        "outline": {
            "title": "Repaired title",
            "sections": [
                {
                    "section_id": "section_01_0123456789",
                    "title": "Introduction",
                    "purpose": "Explain",
                    "block_kinds": ["paragraph"],
                    "source_ids": [],
                }
            ],
        },
        "blocks": [
            {"block_id": "paragraph_001", "kind": "paragraph", "text": "accepted repaired content"}
        ],
        "accepted_section_ids": ["section_01_0123456789"],
        "repair_used": False,
    }
    outline = parse_document_outline(result["outline"], allowed_source_ids=frozenset())
    result["outline"] = outline.payload()
    result["accepted_section_ids"] = [outline.sections[0].section_id]
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [1, 3])
async def test_complete_resume_preserves_draft_version_without_model_calls(monkeypatch, version):
    restored = restore_authoring_checkpoint(_payload(version), citations=None, evidence=None)
    assert restored is not None
    model = AsyncMock(side_effect=AssertionError("accepted_section_must_not_be_reauthored"))
    monkeypatch.setattr(runtime, "invoke_model_call", model)
    saved = []

    async def checkpoint(value):
        saved.append(value.payload())

    result = await runtime.author_semantic_draft_result(
        normalize_brief("Create a report"),
        "qualified-model",
        execution=SimpleNamespace(provider_snapshot=None),
        citations=None,
        resume=restored,
        checkpoint=checkpoint,
    )
    assert result.accepted
    assert result.draft.version == version
    assert result.draft.blocks[0].text == "accepted repaired content"
    assert all(value["draft_version"] == version for value in saved)
    model.assert_not_awaited()


@pytest.mark.parametrize("version", [0, -1, True, "3", 1_000_001])
def test_invalid_checkpoint_draft_version_is_not_admitted(version):
    assert restore_authoring_checkpoint(_payload(version), citations=None, evidence=None) is None


def test_legacy_checkpoint_defaults_to_initial_draft_version():
    payload = _payload(1)
    payload.pop("draft_version")
    restored = restore_authoring_checkpoint(payload, citations=None, evidence=None)
    assert restored is not None
    assert restored.draft_version == 1
