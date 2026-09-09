from __future__ import annotations

from types import SimpleNamespace

import pytest
from application.files import FileService


@pytest.mark.asyncio
async def test_text_write_cannot_masquerade_as_pdf() -> None:
    calls = []

    async def run(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout="__OK__", truncated=False)

    async def revision(_item):
        return "revision-1"

    async def snapshot(_item, _kind):
        return {}

    service = FileService(run, revision, snapshot)
    item = SimpleNamespace(policy=SimpleNamespace(root="/workspace"))

    with pytest.raises(ValueError, match="typed generator"):
        await service.write(
            item,
            path="test.pdf",
            content="тест",
            expected_revision="revision-1",
            snapshot_user_edit=False,
        )

    assert calls == []
