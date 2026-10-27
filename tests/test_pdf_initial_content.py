from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from service.infrastructure import workspace_client
from service.services.chat.application.documents import initial_content as module
from service.services.chat.domain.documents.preparation import PdfPreparationUnavailable

pytestmark = pytest.mark.asyncio


@pytest.fixture
def setup(monkeypatch):
    ref = {"workspace_id": "a" * 32, "token": "PRIVATE"}
    created = {"path": "documents/default", "revision": "fresh-scaffold"}
    rendered = {
        "files": {"main.tex": "renderer-owned", ".gpthub-authoring.json": "managed"},
        "authoring_version": 1,
        "draft_digest": "a" * 64,
        "expected_source_digest": "b" * 64,
    }
    render = AsyncMock(return_value=rendered)
    current = AsyncMock(return_value=ref)
    publish = AsyncMock(return_value={"authoring_version": 1})
    monkeypatch.setattr(module, "render_owned_edit", render)
    monkeypatch.setattr(module, "current_pdf_binding", current)
    monkeypatch.setattr(workspace_client, "publish_document_source", publish)
    return SimpleNamespace(**locals())


async def seed(s):
    return await module.initialize_first_pdf_document(
        s.ref, s.created, 7, config=object(), redis=object()
    )


async def test_fresh_scaffold_uses_existing_deterministic_renderer_and_digest_cas(setup):
    s = setup
    assert await seed(s)
    s.render.assert_awaited_once()
    payload = s.render.await_args.args[2]
    assert payload.path == s.created["path"] and payload.expected_revision == "fresh-scaffold"
    assert payload.authoring_version == 0 and payload.draft_digest is None
    assert payload.draft["title"] == "Новый документ"
    s.publish.assert_awaited_once_with(
        s.ref,
        path=s.created["path"],
        files=s.rendered["files"],
        authoring_version=1,
        draft_digest="a" * 64,
        expected_revision="fresh-scaffold",
        expected_source_digest="b" * 64,
        fence=7,
    )
    assert s.current.await_count == 2


@pytest.mark.parametrize("error", [HTTPException(409), HTTPException(503)])
async def test_changed_source_or_renderer_outage_keeps_source_only_scaffold(setup, error):
    s = setup
    s.render.side_effect = error
    assert not await seed(s)
    s.publish.assert_not_awaited()


@pytest.mark.parametrize(
    "key,value",
    [
        ("expected_source_digest", None),
        ("draft_digest", "bad"),
        ("authoring_version", True),
        ("authoring_version", 2),
    ],
)
async def test_automatic_initial_content_requires_exact_proof_not_a_missing_digest(
    setup, key, value
):
    s = setup
    s.rendered[key] = value
    assert not await seed(s)
    s.publish.assert_not_awaited()


async def test_lost_publication_ack_is_not_retried_or_claimed_as_semantic_readiness(setup):
    s = setup
    s.publish.side_effect = workspace_client.WorkspaceUnavailable("PRIVATE")
    assert not await seed(s)
    s.publish.assert_awaited_once()
    s.render.assert_awaited_once()


async def test_replaced_binding_cannot_receive_initial_source_publication(setup):
    s = setup
    s.current.side_effect = [s.ref, PdfPreparationUnavailable]
    with pytest.raises(PdfPreparationUnavailable):
        await seed(s)
    s.publish.assert_not_awaited()
