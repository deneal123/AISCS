from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from application.documents.builds import DocumentBuildManager
from domain.documents import load_profile_catalog
from infrastructure import document_compiler
from infrastructure.document_compiler import (
    CompilerFailure,
    CompilerResult,
    DockerDocumentCompiler,
    PreparedCompilerJob,
)


class _Compiler:
    def __init__(self) -> None:
        self.published = False
        self.destroyed = False

    async def prepare(self, *_args, **_kwargs):
        return PreparedCompilerJob("build-123456789", "container-private", "paper")

    async def execute(self, *_args, **_kwargs):
        assert _kwargs["final"] is True
        return CompilerResult(
            "ready",
            "",
            {
                "page_count": 2,
                "page_width_pt": 595.3,
                "page_height_pt": 841.9,
                "diagnostics": [],
                "artifact": {"size": 20, "sha256": "a" * 64},
                "preview": {"size": 10, "sha256": "b" * 64},
                "source_bundle": {"size": 30, "sha256": "c" * 64},
                "visual_bundle": {"size": 40, "sha256": "e" * 64},
                "block_pages": [
                    {"block_id": "introduction", "page": 1},
                    {"block_id": "results_slide", "page": 2},
                ],
            },
        )

    async def publish_outputs(self, *_args, **_kwargs):
        self.published = True

    async def destroy(self, _container_id):
        self.destroyed = True

    def health(self):
        return {"compiler_cleanup": 0, "compiler_cleanup_failures": 0}


class _BlockingCompiler(_Compiler):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()

    async def execute(self, *_args, **_kwargs):
        self.entered.set()
        await asyncio.Event().wait()


class _Projects:
    def __init__(self) -> None:
        self.profile = load_profile_catalog().get("generic_article")
        assert self.profile is not None
        self.digest_value = "d" * 64

    async def manifest(self, _item, _path):
        return {"mode": "submission"}, self.profile

    async def digest(self, _item, _path):
        return self.digest_value


class _Registry:
    def __init__(self) -> None:
        self.commands: list[str] = []

    @asynccontextmanager
    async def operation(self, _item):
        yield

    async def exec_raw(self, _item, command, **_kwargs):
        self.commands.append(command)
        return SimpleNamespace(stdout="__OK__")


async def _finished(manager: DocumentBuildManager, build_id: str):
    await asyncio.wait_for(manager._tasks[build_id], timeout=1)
    build = manager.get("workspace-1", build_id)
    assert build is not None
    return build


@pytest.mark.asyncio
async def test_build_publishes_one_atomic_artifact_directory() -> None:
    compiler = _Compiler()
    projects = _Projects()
    registry = _Registry()
    revisions = iter(("rev-1", "rev-1", "rev-1"))

    async def revision(_item):
        return next(revisions)

    manager = DocumentBuildManager(compiler, projects, revision)
    item = SimpleNamespace(
        workspace_id="workspace-1",
        ref=SimpleNamespace(container_id="workspace-container"),
        policy=SimpleNamespace(root="/workspace"),
    )

    started = await manager.start(
        registry,
        item,
        project_path="paper",
        expected_revision="rev-1",
        final=True,
    )
    build = await _finished(manager, started.build_id)

    assert build.state == "visual_pending"
    assert build.output_revision == "rev-1"
    assert [artifact.role for artifact in build.artifacts] == [
        "pdf",
        "thumbnail",
        "source_bundle",
    ]
    assert compiler.published is True
    assert compiler.destroyed is True
    assert build.page_blocks == {1: ("introduction",), 2: ("results_slide",)}
    command = next(
        command for command in registry.commands if "mv /workspace/.gpthub-document" in command
    )
    assert "mv /workspace/.gpthub-document/build-123456789" in command
    assert "/workspace/paper/artifacts/build-123456789" in command
    assert "mv /workspace/.gpthub-document/build-123456789/document.pdf" not in command


@pytest.mark.asyncio
async def test_visual_diagnostic_uses_unambiguous_page_block_provenance() -> None:
    compiler = _Compiler()
    manager = DocumentBuildManager(compiler, _Projects(), lambda _item: _value("rev-1"))
    registry = _Registry()
    item = SimpleNamespace(
        workspace_id="workspace-1",
        ref=SimpleNamespace(container_id="workspace-container"),
        policy=SimpleNamespace(root="/workspace"),
    )
    started = await manager.start(
        registry, item, project_path="paper", expected_revision="rev-1", final=True
    )
    build = await _finished(manager, started.build_id)

    audited = await manager.complete_visual_audit(
        registry,
        item,
        build.build_id,
        source_digest=build.source_digest,
        artifact_sha256="a" * 64,
        passed=False,
        retryable=False,
        audit_version=1,
        diagnostics=[{"code": "visual_clipping", "page": 2, "count": 1}],
    )

    visual = next(item for item in audited.diagnostics if item.code == "visual_clipping")
    assert visual.line == 2
    assert visual.block_id == "results_slide"


@pytest.mark.asyncio
async def test_source_change_discards_compiler_result_without_publication() -> None:
    compiler = _Compiler()
    projects = _Projects()
    registry = _Registry()
    revisions = iter(("rev-1", "rev-2"))

    async def revision(_item):
        return next(revisions)

    manager = DocumentBuildManager(compiler, projects, revision)
    item = SimpleNamespace(
        workspace_id="workspace-1",
        ref=SimpleNamespace(container_id="workspace-container"),
        policy=SimpleNamespace(root="/workspace"),
    )

    started = await manager.start(
        registry,
        item,
        project_path="paper",
        expected_revision="rev-1",
        final=True,
    )
    build = await _finished(manager, started.build_id)

    assert build.state == "failed"
    assert build.failure_code == "source_changed"
    assert compiler.published is False
    assert not any("/artifacts/build-123456789" in command for command in registry.commands)
    assert compiler.destroyed is True


@pytest.mark.asyncio
async def test_explicit_build_cancel_is_distinct_from_process_interruption() -> None:
    compiler = _BlockingCompiler()
    manager = DocumentBuildManager(compiler, _Projects(), lambda _item: _value("rev-1"))
    registry = _Registry()
    item = SimpleNamespace(
        workspace_id="workspace-1",
        ref=SimpleNamespace(container_id="workspace-container"),
        policy=SimpleNamespace(root="/workspace"),
    )
    started = await manager.start(
        registry, item, project_path="paper", expected_revision="rev-1", final=True
    )
    await compiler.entered.wait()

    cancelled = await manager.cancel(registry, item, item.workspace_id, started.build_id)

    assert cancelled is not None
    assert (cancelled.state, cancelled.failure_code) == ("cancelled", "build_cancelled")


@pytest.mark.asyncio
async def test_process_task_cancellation_is_recoverable_interruption() -> None:
    compiler = _BlockingCompiler()
    manager = DocumentBuildManager(compiler, _Projects(), lambda _item: _value("rev-1"))
    registry = _Registry()
    item = SimpleNamespace(
        workspace_id="workspace-1",
        ref=SimpleNamespace(container_id="workspace-container"),
        policy=SimpleNamespace(root="/workspace"),
    )
    started = await manager.start(
        registry, item, project_path="paper", expected_revision="rev-1", final=True
    )
    await compiler.entered.wait()
    task = manager._tasks[started.build_id]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    interrupted = manager.get(item.workspace_id, started.build_id)
    assert interrupted is not None
    assert (interrupted.state, interrupted.failure_code) == ("failed", "build_interrupted")


async def _value(value):
    return value


@pytest.mark.asyncio
async def test_reconcile_preserves_live_job_and_removes_expired_or_legacy(monkeypatch) -> None:
    removed: list[str] = []

    async def command(*argv, **_kwargs):
        if argv[1:3] == ("ps", "-aq"):
            return 0, b"fresh\nexpired\nlegacy\n"
        if argv[1:3] == ("inspect", "--format"):
            template, container_id = argv[3], argv[4]
            if "Labels" in template:
                if container_id == "fresh":
                    return 0, b'{"gpthub.document.expires_at":"9999999999"}'
                if container_id == "expired":
                    return 0, b'{"gpthub.document.expires_at":"1"}'
                return 0, b'{"gpthub.document":"1"}'
            return 0, b"true"
        if argv[1:3] == ("rm", "-f"):
            removed.append(argv[3])
            return 0, b""
        raise AssertionError(argv)

    monkeypatch.setattr(document_compiler, "_command", command)
    compiler = DockerDocumentCompiler()

    assert await compiler.reconcile() == 2
    assert removed == ["expired", "legacy"]
    assert compiler.health() == {
        "compiler_cleanup": 2,
        "compiler_cleanup_failures": 0,
    }


@pytest.mark.asyncio
async def test_compiler_source_snapshot_excludes_runtime_output(monkeypatch) -> None:
    piped: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    async def command(*argv, **_kwargs):
        if argv[1:3] == ("exec", "workspace-container"):
            return 0, b""
        if argv[1] == "create":
            return 0, b"compiler-container\n"
        if argv[1:3] == ("start", "compiler-container"):
            return 0, b""
        raise AssertionError(argv)

    async def pipe(left, right, **_kwargs):
        piped.append((left, right))

    monkeypatch.setattr(document_compiler, "_command", command)
    monkeypatch.setattr(document_compiler, "_pipe", pipe)
    compiler = DockerDocumentCompiler()

    prepared = await compiler.prepare(
        SimpleNamespace(container_id="workspace-container"),
        workspace_root="/workspace",
        project_path="/workspace/documents/paper",
    )

    assert prepared.container_id == "compiler-container"
    tar_command = piped[0][0]
    assert "--exclude=paper/.git" in tar_command
    assert "--exclude=paper/.gpthub-document" in tar_command
    assert "--exclude=paper/artifacts" in tar_command


@pytest.mark.asyncio
async def test_compiler_streams_tmpfs_outputs_through_container_tar(monkeypatch) -> None:
    piped: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    async def command(*argv, **_kwargs):
        assert argv[:3] == ("docker", "exec", "workspace-container")
        return 0, b""

    async def pipe(left, right, **_kwargs):
        piped.append((left, right))

    monkeypatch.setattr(document_compiler, "_command", command)
    monkeypatch.setattr(document_compiler, "_pipe", pipe)
    compiler = DockerDocumentCompiler()

    await compiler.publish_outputs(
        PreparedCompilerJob("build-123", "compiler-container", "paper"),
        SimpleNamespace(container_id="workspace-container"),
        staging_dir="/workspace/.gpthub-document/build-123",
    )

    producer, consumer = piped[0]
    assert producer == (
        "docker",
        "exec",
        "compiler-container",
        "tar",
        "-C",
        "/output",
        "-cf",
        "-",
        ".",
    )
    assert consumer[:4] == ("docker", "exec", "-i", "workspace-container")


@pytest.mark.asyncio
async def test_compiler_rejects_unsafe_source_before_container_create(monkeypatch) -> None:
    async def command(*_argv, **_kwargs):
        return 3, b""

    monkeypatch.setattr(document_compiler, "_command", command)
    compiler = DockerDocumentCompiler()

    with pytest.raises(CompilerFailure) as error:
        await compiler.prepare(
            SimpleNamespace(container_id="workspace-container"),
            workspace_root="/workspace",
            project_path="/workspace/documents/paper",
        )

    assert error.value.code == "invalid_project"
