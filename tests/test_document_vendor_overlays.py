from __future__ import annotations

import hashlib
import io
import json
import stat
import tarfile
import zipfile
from types import SimpleNamespace

import pytest
from application.documents.vendor_overlays import (
    DocumentVendorOverlayService,
    VendorOverlayError,
    validate_vendor_archive,
)


def _archive(
    *,
    package_id: str = "journal-kit",
    style: bytes = b"\\NeedsTeXFormat{LaTeX2e}\n",
    extra_manifest: str = "",
) -> bytes:
    output = io.BytesIO()
    manifest = (
        "schema_version = 1\n"
        f'package_id = "{package_id}"\n'
        'version = "1.0"\n'
        'license = "LPPL-1.3c"\n'
        'entry_files = ["journal.cls"]\n'
        f"{extra_manifest}"
    )
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("vendor.toml", manifest)
        archive.writestr("journal.cls", style)
    return output.getvalue()


def _error_code(payload: bytes) -> str:
    with pytest.raises(VendorOverlayError) as raised:
        validate_vendor_archive(payload)
    return raised.value.code


def test_valid_archive_is_normalized_to_deterministic_untrusted_package() -> None:
    payload = _archive()
    package = validate_vendor_archive(payload)

    assert package.package_id == "journal-kit"
    assert package.digest == hashlib.sha256(payload).hexdigest()
    assert package.public_dict()["trusted"] is False
    assert package.public_dict()["export_allowed"] is False
    with tarfile.open(fileobj=io.BytesIO(package.archive)) as archive:
        names = archive.getnames()
        assert names == ["journal.cls", "vendor.toml", ".gpthub-overlay.toml"]
        metadata = archive.extractfile(".gpthub-overlay.toml")
        assert metadata is not None
        assert b"export_allowed = false" in metadata.read()


def test_archive_rejects_traversal_symlink_and_executable_tex_primitives() -> None:
    traversal = io.BytesIO()
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("vendor.toml", "schema_version = 1\n")
        archive.writestr("../escape.cls", "unsafe")
    assert _error_code(traversal.getvalue()) == "vendor_archive_invalid"

    symlink = io.BytesIO()
    with zipfile.ZipFile(symlink, "w") as archive:
        archive.writestr("vendor.toml", "schema_version = 1\n")
        info = zipfile.ZipInfo("journal.cls")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target")
    assert _error_code(symlink.getvalue()) == "vendor_unsafe"

    assert _error_code(_archive(style=b"\\write18{curl example.test}")) == "vendor_unsafe"


def test_manifest_cannot_set_runtime_policy_or_reference_missing_entry() -> None:
    assert _error_code(_archive(extra_manifest='engine = "lualatex"\n')) == (
        "vendor_manifest_invalid"
    )

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "vendor.toml",
            "schema_version = 1\n"
            'package_id = "journal-kit"\n'
            'version = "1.0"\n'
            'license = "LPPL-1.3c"\n'
            'entry_files = ["missing.cls"]\n',
        )
        archive.writestr("journal.cls", "safe")
    assert _error_code(output.getvalue()) == "vendor_manifest_invalid"


@pytest.mark.asyncio
async def test_service_rechecks_revision_and_creates_exactly_one_safe_snapshot() -> None:
    payload = _archive()
    commands: list[tuple[str, bytes | None]] = []
    snapshots: list[str] = []

    async def run(_item, command: str, *, stdin_payload: bytes | None = None):
        commands.append((command, stdin_payload))
        return SimpleNamespace(stdout="__IMPORTED__")

    async def snapshot(_item, snapshot_type: str):
        snapshots.append(snapshot_type)
        return {"committed": True}

    async def revision(_item):
        return "rev-1"

    async def fetcher(_url: str):
        return payload

    projects = SimpleNamespace(manifest=lambda *_args: _async_value(({}, object())))
    service = DocumentVendorOverlayService(run, snapshot, revision, projects, fetcher)
    item = SimpleNamespace(policy=SimpleNamespace(root="/workspace"))

    result = await service.apply(
        item,
        path="documents/paper",
        source_url="https://files.example/vendor.zip",
        source_sha256=hashlib.sha256(payload).hexdigest(),
        expected_revision="rev-1",
    )

    assert result["outcome"] == "imported"
    assert result["revision_changed"] is True
    assert snapshots == ["document_vendor"]
    assert len(commands) == 1
    assert commands[0][1] is not None
    assert "mv " in commands[0][0]
    assert "journal-kit" in commands[0][0]
    assert "[ -L /workspace/documents/paper ]" in commands[0][0]
    assert "[ -L /workspace/documents/paper/vendor/journal-kit ]" in commands[0][0]


@pytest.mark.asyncio
async def test_list_exposes_only_safe_overlay_metadata() -> None:
    raw = {
        "package_id": "journal-kit",
        "version": "1.0",
        "license": "LPPL-1.3c",
        "digest": "a" * 64,
        "file_count": 3,
        "expanded_bytes": 4096,
        "trusted": False,
        "export_allowed": False,
    }

    async def run(_item, _command: str):
        return SimpleNamespace(stdout=json.dumps([raw]))

    service = DocumentVendorOverlayService(
        run,
        lambda *_args: _async_value({}),
        lambda *_args: _async_value("rev-1"),
        SimpleNamespace(manifest=lambda *_args: _async_value(({}, object()))),
    )
    item = SimpleNamespace(policy=SimpleNamespace(root="/workspace"))

    rows = await service.list(item, "documents/paper")

    assert rows == [
        {
            "package_id": "journal-kit",
            "version": "1.0",
            "license": "LPPL-1.3c",
            "file_count": 3,
            "trusted": False,
            "export_allowed": False,
        }
    ]
    assert "digest" not in rows[0]
    assert "expanded_bytes" not in rows[0]


@pytest.mark.asyncio
async def test_list_drops_tampered_overlay_metadata() -> None:
    rows = [
        {
            "package_id": "journal-kit",
            "version": "1.0",
            "license": "unsafe\nmetadata",
            "file_count": 2,
            "trusted": True,
            "export_allowed": True,
        },
        {
            "package_id": "safe-kit",
            "version": "2.0",
            "license": "LPPL-1.3c",
            "file_count": 2,
            "trusted": True,
            "export_allowed": True,
        },
    ]

    async def run(_item, command: str):
        assert "path.parent.is_symlink()" in command
        return SimpleNamespace(stdout=json.dumps(rows))

    service = DocumentVendorOverlayService(
        run,
        lambda *_args: _async_value({}),
        lambda *_args: _async_value("rev-1"),
        SimpleNamespace(manifest=lambda *_args: _async_value(({}, object()))),
    )

    assert await service.list(
        SimpleNamespace(policy=SimpleNamespace(root="/workspace")), "documents/paper"
    ) == [
        {
            "package_id": "safe-kit",
            "version": "2.0",
            "license": "LPPL-1.3c",
            "file_count": 2,
            "trusted": False,
            "export_allowed": False,
        }
    ]


@pytest.mark.asyncio
async def test_service_refuses_stale_revision_before_download() -> None:
    fetched = False

    async def revision(_item):
        return "newer"

    async def fetcher(_url: str):
        nonlocal fetched
        fetched = True
        return _archive()

    service = DocumentVendorOverlayService(
        lambda *_args, **_kwargs: _async_value(SimpleNamespace(stdout="")),
        lambda *_args: _async_value({}),
        revision,
        SimpleNamespace(manifest=lambda *_args: _async_value(({}, object()))),
        fetcher,
    )
    item = SimpleNamespace(policy=SimpleNamespace(root="/workspace"))
    with pytest.raises(VendorOverlayError, match="revision_conflict"):
        await service.apply(
            item,
            path="documents/paper",
            source_url="https://files.example/vendor.zip",
            source_sha256=None,
            expected_revision="old",
        )
    assert fetched is False


async def _async_value(value):
    return value
