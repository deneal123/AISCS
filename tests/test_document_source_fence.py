import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.responses import JSONResponse
from presentation.routes.contracts import DocumentSourceRequest
from presentation.routes.documents import DocumentRouteDependencies, create_documents_router


@pytest.mark.parametrize(
    "pinned,changed,status",
    [
        ("a" * 64, False, 200),
        ("a" * 64, True, 409),
        (None, True, 200),
    ],
)
@pytest.mark.asyncio
async def test_publication_checks_source_fence_inside_the_workspace_operation(
    pinned, changed, status
):
    locked = False
    item = object()

    @asynccontextmanager
    async def operation(current):
        nonlocal locked
        assert current is item
        locked = True
        try:
            yield
        finally:
            locked = False

    async def project_status(current, path):
        assert locked and current is item and path == "documents/paper"
        return {"source_digest": ("b" if changed else "a") * 64}

    async def publish(current, **_kwargs):
        assert locked and current is item
        return {"outcome": "published"}

    writer = AsyncMock(side_effect=publish)
    projects = SimpleNamespace(status=AsyncMock(side_effect=project_status))
    common = SimpleNamespace(
        auth=lambda _: None,
        owned=lambda *_: (item, None),
        coordination_guard=AsyncMock(return_value=None),
        guard_denied=lambda _: False,
        registry=lambda: SimpleNamespace(operation=operation),
        revision=AsyncMock(return_value="r1"),
        error=lambda code, message, status: JSONResponse({"error": code}, status_code=status),
    )
    router = create_documents_router(
        DocumentRouteDependencies(
            common=common,
            projects=projects,
            sources=SimpleNamespace(publish=writer),
            catalog=None,
            checkpoints=None,
            vendors=None,
            builds=None,
        )
    )
    handler = next(route.endpoint for route in router.routes if route.name == "publish_source")
    result = await handler(
        "workspace",
        DocumentSourceRequest(
            user_id="owner",
            token="private",
            path="documents/paper",
            files={"main.tex": "new"},
            authoring_version=1,
            draft_digest="c" * 64,
            expected_revision="r1",
            expected_source_digest=pinned,
            coordination_fence=1,
        ),
    )
    assert not locked
    if status == 409:
        assert result.status_code == 409
        assert json.loads(result.body) == {"error": "source_changed"}
        writer.assert_not_awaited()
    else:
        assert result == {"outcome": "published"}
        writer.assert_awaited_once()
    assert projects.status.await_count == (1 if pinned else 0)
