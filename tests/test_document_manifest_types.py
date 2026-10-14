"""Durable build data must not regain validity through truthiness/coercion."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.build_store import INVENTORY_COMPLETE, BuildManifestStore
from domain.documents import DocumentBuild


def manifest():
    return DocumentBuild(
        "build-owned",
        "owned",
        "/workspace/paper",
        "generic_document",
        1,
        "revision",
        "d" * 64,
        "draft",
        False,
    ).manifest_dict()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": True},
        {"final": "false"},
        {"final": 1},
        {"mode": "unknown"},
        {"created_at": float("nan")},
        {"completed_at": float("inf")},
        {"visual_audit_claimed_at": float("nan")},
        {"page_width_pt": float("inf")},
        {"page_height_pt": float("nan")},
        {"page_count": True},
        {"page_count": 1.5},
        {"authoring_version": -1},
    ],
)
async def test_invalid_typed_manifest_never_enters_recovered_inventory(changes):
    raw = {**manifest(), **changes}
    registry = SimpleNamespace(
        exec_raw=AsyncMock(
            return_value=SimpleNamespace(
                stdout=json.dumps(raw) + "\n" + INVENTORY_COMPLETE, exit_code=0
            )
        )
    )
    item = SimpleNamespace(workspace_id="owned", policy=SimpleNamespace(root="/workspace"))
    with pytest.raises(RuntimeError, match="^build manifest inventory invalid$"):
        await BuildManifestStore().load(registry, item)


def test_generated_manifest_retains_boolean_and_numeric_types():
    raw = manifest()
    recovered = DocumentBuild.from_manifest(raw)
    assert recovered.final is False
    assert recovered.manifest_dict() == raw
