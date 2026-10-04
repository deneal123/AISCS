from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from types import SimpleNamespace

import pytest
from application.documents.projects import DocumentProjectError, DocumentProjectService
from application.documents.sources import _archive
from domain.documents import load_profile_catalog


def _item():
    return SimpleNamespace(policy=SimpleNamespace(root="/workspace"))


def _manifest(*, digest: str | None = None) -> dict[str, object]:
    draft = {
        "schema_version": 1,
        "version": 4,
        "blocks": [
            {"block_id": "intro-001", "kind": "paragraph", "text": "safe"},
            {"block_id": "table-001", "kind": "table", "rows": []},
        ],
    }
    actual = hashlib.sha256(
        json.dumps(draft, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "draft_version": 4,
        "draft_digest": digest or actual,
        "intent": {"kind": "report", "title": "Safe"},
        "draft": draft,
        "block_files": {
            "content/intro.tex": "intro-001",
            "content/table.tex": "table-001",
            "content/unknown.tex": "unknown-001",
        },
    }


def _legacy_manifest() -> dict[str, object]:
    raw = _manifest()
    draft = dict(raw["draft"])
    draft["blocks"] = [{**block, "id": block["block_id"]} for block in draft["blocks"]]
    for block in draft["blocks"]:
        block.pop("block_id", None)
    raw["draft"] = draft
    raw["draft_digest"] = hashlib.sha256(
        json.dumps(draft, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return raw


def _service(raw: dict[str, object]) -> DocumentProjectService:
    encoded = base64.b64encode(
        json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode()
    ).decode()

    async def run(_item, _command, **_kwargs):
        return SimpleNamespace(stdout=encoded)

    async def snapshot(*_args):
        return {}

    service = DocumentProjectService(run, snapshot, load_profile_catalog())

    async def manifest(*_args):
        profile = service.catalog.get("generic_report")
        assert profile is not None
        return {}, profile

    service.manifest = manifest  # type: ignore[method-assign]
    return service


@pytest.mark.asyncio
async def test_authoring_state_verifies_digest_and_reverses_known_block_paths() -> None:
    result = await _service(_manifest()).authoring_state(_item(), "documents/report")

    assert result["authoring_version"] == 4
    assert result["block_files"] == {
        "intro-001": "content/intro.tex",
        "table-001": "content/table.tex",
    }


@pytest.mark.asyncio
async def test_authoring_state_rejects_tampered_semantic_draft() -> None:
    with pytest.raises(DocumentProjectError, match="authoring_invalid"):
        await _service(_manifest(digest="0" * 64)).authoring_state(_item(), "documents/report")


@pytest.mark.asyncio
async def test_authoring_state_reads_the_unreleased_legacy_id_shape() -> None:
    result = await _service(_legacy_manifest()).authoring_state(_item(), "documents/report")

    assert result["block_files"]["intro-001"] == "content/intro.tex"


def _source_only_manifest():
    payload, _ = _archive(
        {"main.tex": "source-only text"},
        authoring_version=1,
        draft_digest="a" * 64,
    )
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        stream = archive.extractfile(".gpthub-authoring.json")
        assert stream is not None
        return json.load(stream)


@pytest.mark.asyncio
async def test_published_source_only_bundle_can_build_without_claiming_semantic_draft():
    service = _service(_source_only_manifest())
    assert await service.authoring(_item(), "documents/report") == (0, "")
    with pytest.raises(DocumentProjectError, match="authoring_missing"):
        await service.authoring_state(_item(), "documents/report")
    assert await service.block_provenance(_item(), "documents/report") == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [
        {"draft_version": True},
        {"draft_digest": "invalid"},
        {"schema_version": 2},
        {"schema_version": True},
        {"draft": None},
        {"intent": {}},
    ],
)
async def test_source_only_compatibility_does_not_hide_corrupt_or_semantic_manifests(changed):
    service = _service({**_source_only_manifest(), **changed})
    with pytest.raises(DocumentProjectError, match="authoring_invalid"):
        await service.authoring(_item(), "documents/report")
