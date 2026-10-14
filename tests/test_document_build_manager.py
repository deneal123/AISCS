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
        job = PreparedCompilerJob("build-123456789", "container-private", "paper")
        await _kwargs["before_create"](job.job_ref)
        await _kwargs["on_allocated"](job)
        return job

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

    async def artifact_facts(self, _ref, path, *, max_bytes):
        facts = {
            "document.pdf": ("a" * 64, 20),
            "preview.png": ("b" * 64, 10),
            "source.zip": ("c" * 64, 30),
            "visual-pages.tar": ("e" * 64, 40),
        }
        value = facts[path.rsplit("/", 1)[-1]]
        assert max_bytes == value[1]
        return value

    async def destroy(self, _container_id):
        self.destroyed = True
        return True

    def health(self):
        return {"compiler_cleanup": 0, "compiler_cleanup_failures": 0}


class _BlockingCompiler(_Compiler):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()

    async def execute(self, *_args, **_kwargs):
        self.entered.set()
        await asyncio.Event().wait()


class _FailedAuditCompiler(_Compiler):
    async def execute(self, *_args, **_kwargs):
        return CompilerResult(
            "failed",
            "audit_failed",
            {"diagnostics": [{"severity": "error", "code": "required_section", "count": 2}]},
        )


class _Projects:
    def __init__(self) -> None:
        self.profile = load_profile_catalog().get("generic_article")
        assert self.profile is not None
        self.digest_value = "d" * 64

    async def manifest(self, _item, _path):
        return {"mode": "submission"}, self.profile

    async def digest(self, _item, _path):
        return self.digest_value


class _DelayedProvenanceProjects(_Projects):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def block_provenance(self, _item, _path):
        self.entered.set()
        await self.release.wait()
        return {}


class _Registry:
    def __init__(self) -> None:
        self.commands: list[str] = []

    @asynccontextmanager
    async def operation(self, _item):
        yield

    async def exec_raw(self, _item, command, **_kwargs):
        import base64

        self.commands.append(command)
        if "-maxdepth 1 -name '*.json'" in command:
            return SimpleNamespace(stdout="__GPTHUB_MANIFESTS_COMPLETE__\n", exit_code=0)
        if "/.gpthub-document/jobs/" in command and "stdin_payload" in _kwargs:
            size = len(base64.b64decode(_kwargs["stdin_payload"]))
            return SimpleNamespace(stdout=f"__OK__ {size}\n", exit_code=0)
        if "rm -f" in command and "/.gpthub-document/jobs/" in command:
            return SimpleNamespace(stdout="__OK__\n", exit_code=0)
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
    assert build.compiler_ref == ""
    assert build.page_blocks == {1: ("introduction",), 2: ("results_slide",)}
    command = next(
        command for command in registry.commands if "mv /workspace/.gpthub-document" in command
    )
    assert "mv /workspace/.gpthub-document/build-123456789" in command
    assert "/workspace/paper/artifacts/build-123456789" in command
    assert "mv /workspace/.gpthub-document/build-123456789/document.pdf" not in command


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename", ["document.pdf", "preview.png", "source.zip", "visual-pages.tar"]
)
@pytest.mark.parametrize("mismatch", ["digest", "size"])
async def test_mismatched_staged_artifact_never_publishes_directory(filename, mismatch):
    class MismatchedCompiler(_Compiler):
        async def artifact_facts(self, ref, path, *, max_bytes):
            digest, size = await super().artifact_facts(ref, path, max_bytes=max_bytes)
            if path.rsplit("/", 1)[-1] == filename:
                return ("f" * 64, size) if mismatch == "digest" else (digest, size - 1)
            return digest, size

    compiler = MismatchedCompiler()
    manager = DocumentBuildManager(compiler, _Projects(), lambda _item: _value("rev-1"))
    registry = _Registry()
    item = SimpleNamespace(
        workspace_id="workspace-1",
        ref=SimpleNamespace(container_id="fixture"),
        policy=SimpleNamespace(root="/workspace"),
    )
    started = await manager.start(
        registry, item, project_path="paper", expected_revision="rev-1", final=True
    )
    build = await _finished(manager, started.build_id)
    assert build.state == "failed"
    assert build.failure_code == "artifact_invalid"
    assert build.artifacts == ()
    assert not any("mv /workspace/.gpthub-document" in command for command in registry.commands)
    assert compiler.destroyed is True


@pytest.mark.asyncio
async def test_terminal_failure_is_latched_only_after_diagnostics_are_complete() -> None:
    projects = _DelayedProvenanceProjects()
    manager = DocumentBuildManager(_FailedAuditCompiler(), projects, lambda _item: _value("rev-1"))
    registry = _Registry()
    item = SimpleNamespace(
        workspace_id="workspace-1",
        ref=SimpleNamespace(container_id="workspace-container"),
        policy=SimpleNamespace(root="/workspace"),
    )

    started = await manager.start(
        registry, item, project_path="paper", expected_revision="rev-1", final=True
    )
    await projects.entered.wait()

    observed = manager.get(item.workspace_id, started.build_id)
    assert observed is not None
    assert observed.state == "building"
    assert observed.failure_code == ""
    assert observed.diagnostics == ()

    projects.release.set()
    failed = await _finished(manager, started.build_id)
    assert failed.state == "failed"
    assert [item.code for item in failed.diagnostics] == ["required_section"]


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
async def test_reconcile_preserves_live_and_unknown_legacy_but_removes_expired(monkeypatch) -> None:
    removed: list[str] = []
    fresh, expired, legacy = "a" * 64, "b" * 64, "c" * 64

    async def command(*argv, **_kwargs):
        if argv[1:3] == ("ps", "-aq"):
            return 0, f"{fresh}\n{expired}\n{legacy}\n".encode()
        if argv[1:3] == ("inspect", "--format"):
            template, container_id = argv[3], argv[4]
            if "Labels" in template:
                if container_id == fresh:
                    return 0, b'{"gpthub.document.expires_at":"9999999999"}'
                if container_id == expired:
                    return 0, b'{"gpthub.document.expires_at":"1"}'
                return 0, b'{"gpthub.document":"1"}'
            return 0, b"true"
        if argv[1:3] == ("rm", "-f"):
            removed.append(argv[3])
            return 0, b""
        raise AssertionError(argv)

    monkeypatch.setattr(document_compiler, "_command", command)
    compiler = DockerDocumentCompiler()

    assert await compiler.reconcile() == 1
    assert removed == [expired]
    assert compiler.health() == {
        "compiler_cleanup": 1,
        "compiler_cleanup_failures": 1,
        "compiler_preparation_pending": 0,
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
    assert producer[:5] == ("docker", "exec", "compiler-container", "/bin/sh", "-c")
    assert "document.pdf report.json" in producer[-1]
    assert "preview.png source.zip visual-pages.tar" in producer[-1]
    assert '"$@"' in producer[-1]
    assert consumer[:4] == ("docker", "exec", "-i", "workspace-container")
    assert consumer[4:6] == ("python3", "-c")
    assert "O_NOFOLLOW" in consumer[6] and "member_name" in consumer[6]
    assert consumer[7] == "/workspace/.gpthub-document/build-123"


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
