from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from application.documents.vendor_overlays import VendorOverlayError, VendorProfileDeclaration
from application.documents.vendor_profiles import DocumentVendorProfileService
from domain.documents import load_profile_catalog


class _Registry:
    @asynccontextmanager
    async def operation(self, _item):
        yield


class _Compiler:
    def __init__(self, status: str = "ready") -> None:
        self.status = status
        self.destroyed: list[str] = []

    async def prepare(self, _ref, *, workspace_root, project_path):
        assert workspace_root == "/workspace"
        assert ".gpthub-document/vendor-profile-" in project_path
        return SimpleNamespace(container_id="compiler-1")

    async def execute(self, _job, *, entrypoint, engine, final):
        assert (entrypoint, engine, final) == ("main.tex", "xelatex", False)
        return SimpleNamespace(status=self.status)

    async def destroy(self, container_id):
        self.destroyed.append(container_id)
        return True


def _declaration() -> VendorProfileDeclaration:
    return VendorProfileDeclaration(
        template_entrypoint="template.tex",
        documentclass="vendor-article",
        styles=("vendor.cls",),
        bibliography_style="plain",
        content_contract="article",
        paper="a4",
        orientation="portrait",
        max_pages=None,
        required_sections=("abstract", "references"),
    )


def _service(status: str = "ready", *, snapshot_result: dict | None = None):
    commands: list[str] = []
    snapshots: list[str] = []
    revisions = iter(("rev-1", "rev-1", "rev-2"))
    profile = load_profile_catalog().get("generic_article")
    assert profile is not None

    async def run(_item, command, *, stdin_payload=None):
        commands.append(command)
        if "rm -rf" in command and "tar -C" in command:
            return SimpleNamespace(stdout="__STAGED__")
        if "mv " in command and "__OK__" in command:
            return SimpleNamespace(stdout="__OK__")
        return SimpleNamespace(stdout="")

    async def snapshot(_item, kind):
        snapshots.append(kind)
        return snapshot_result or {"committed": True}

    async def revision(_item):
        return next(revisions)

    projects = SimpleNamespace(
        manifest=lambda *_args: _value(({"mode": "draft", "locale": "ru-RU"}, profile))
    )
    vendors = SimpleNamespace(profile=lambda *_args: _value(_declaration()))
    compiler = _Compiler(status)
    service = DocumentVendorProfileService(run, snapshot, revision, projects, vendors, compiler)
    return service, compiler, commands, snapshots


@pytest.mark.asyncio
async def test_v2_activation_probes_then_atomically_publishes_a_clone() -> None:
    service, compiler, commands, snapshots = _service()
    item = SimpleNamespace(
        policy=SimpleNamespace(root="/workspace"),
        ref=SimpleNamespace(container_id="workspace-1"),
    )

    result = await service.activate(
        _Registry(),
        item,
        path="documents/source",
        package_id="journal-kit",
        target_path="documents/vendor-copy",
        expected_revision="rev-1",
    )

    assert result["outcome"] == "cloned"
    assert result["path"] == "documents/vendor-copy"
    assert result["content_status"] == "copied"
    assert snapshots == ["document_profile"]
    assert compiler.destroyed == ["compiler-1"]
    assert any("vendor/journal-kit" in command and "__STAGED__" in command for command in commands)
    assert any("documents/vendor-copy" in command and "__OK__" in command for command in commands)


@pytest.mark.asyncio
async def test_failed_probe_removes_stage_and_preserves_source() -> None:
    service, compiler, commands, snapshots = _service("failed")
    item = SimpleNamespace(
        policy=SimpleNamespace(root="/workspace"),
        ref=SimpleNamespace(container_id="workspace-1"),
    )

    with pytest.raises(VendorOverlayError, match="vendor_profile_invalid"):
        await service.activate(
            _Registry(),
            item,
            path="documents/source",
            package_id="journal-kit",
            target_path="documents/vendor-copy",
            expected_revision="rev-1",
        )

    assert snapshots == []
    assert compiler.destroyed == ["compiler-1"]
    assert any(command.startswith("rm -rf") for command in commands)
    assert not any(
        "documents/vendor-copy" in command and "__OK__" in command for command in commands
    )


@pytest.mark.asyncio
async def test_failed_profile_snapshot_removes_only_the_new_clone() -> None:
    service, compiler, commands, snapshots = _service(
        snapshot_result={"committed": False, "reason": "failed"}
    )
    item = SimpleNamespace(
        policy=SimpleNamespace(root="/workspace"),
        ref=SimpleNamespace(container_id="workspace-1"),
    )

    with pytest.raises(VendorOverlayError, match="vendor_profile_invalid"):
        await service.activate(
            _Registry(),
            item,
            path="documents/source",
            package_id="journal-kit",
            target_path="documents/vendor-copy",
            expected_revision="rev-1",
        )

    assert snapshots == ["document_profile"]
    assert compiler.destroyed == ["compiler-1"]
    assert commands[-1] == "rm -rf /workspace/documents/vendor-copy"
    assert not any(command == "rm -rf /workspace/documents/source" for command in commands)


async def _value(value):
    return value
