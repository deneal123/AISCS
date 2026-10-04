"""Docker-backed disposable compiler jobs for Document Forge.

Only this module knows compiler container identifiers. Public failures are
bounded codes and never include Docker output or user-controlled paths.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shlex
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from drivers import ContainerRef

from . import document_processes
from .document_cleanup import compiler_inventory, compiler_state, container_absent

DOCUMENT_IMAGE = os.environ.get("WORKSPACE_DOCUMENT_IMAGE", "gpthub-document-runtime:latest")
MAX_SOURCE_BYTES = int(os.environ.get("WORKSPACE_DOCUMENT_MAX_SOURCE_BYTES", str(32 * 1024 * 1024)))
MAX_ARTIFACT_BYTES = int(
    os.environ.get("WORKSPACE_DOCUMENT_MAX_ARTIFACT_BYTES", str(64 * 1024 * 1024))
)
MAX_VISUAL_BYTES = int(
    os.environ.get("WORKSPACE_DOCUMENT_MAX_VISUAL_BYTES", str(256 * 1024 * 1024))
)
BUILD_TIMEOUT_SEC = float(os.environ.get("WORKSPACE_DOCUMENT_BUILD_TIMEOUT_SEC", "240"))
MEMORY_BYTES = int(os.environ.get("WORKSPACE_DOCUMENT_MEMORY_BYTES", str(1536 * 1024 * 1024)))
PIDS_LIMIT = int(os.environ.get("WORKSPACE_DOCUMENT_PIDS_LIMIT", "384"))
CPUS = float(os.environ.get("WORKSPACE_DOCUMENT_CPUS", "2"))


class CompilerFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PreparedCompilerJob:
    job_ref: str
    container_id: str
    project_name: str


@dataclass(frozen=True, slots=True)
class CompilerResult:
    status: str
    failure_code: str
    report: dict[str, object]


async def _command(*argv: str, timeout: float = 60.0, input_bytes: bytes | None = None):
    try:
        return await document_processes.command(*argv, timeout=timeout, input_bytes=input_bytes)
    except TimeoutError:
        raise CompilerFailure("runtime_unavailable") from None


async def _pipe(left: tuple[str, ...], right: tuple[str, ...], *, timeout: float) -> None:
    try:
        await document_processes.pipe(left, right, timeout=timeout)
    except TimeoutError:
        raise CompilerFailure("runtime_unavailable") from None


class DockerDocumentCompiler:
    """Prepare, execute and drain one compiler container."""

    def __init__(self) -> None:
        self.reconciled_cleanup = 0
        self.cleanup_failures = 0
        self._preparation_cleanup: dict[str, tuple[ContainerRef, str]] = {}
        self._creating: dict[str, asyncio.Task[None]] = {}

    @property
    def pending_preparation_cleanup(self) -> int:
        return len(self._preparation_cleanup)

    @property
    def preparation_cleanup_refs(self) -> frozenset[str]:
        return frozenset(ref for _, ref in self._preparation_cleanup.values())

    async def inventory_refs(self) -> frozenset[str]:
        try:
            return await compiler_inventory(_command)
        except (OSError, ValueError, CompilerFailure):
            raise CompilerFailure("runtime_unavailable") from None

    async def _validate_source(self, workspace_ref: ContainerRef, project_path: str) -> None:
        """Reject links/special files and oversized input before creating a compiler.

        The compiler container contains no tenant credentials, but TeX input is still
        executable data. Following a project-local symlink would make the immutable
        source snapshot depend on files outside the project and would defeat digest
        checks. The command receives the path as an argument, never as shell syntax.
        """

        script = (
            'root="$1"; limit="$2"; '
            'test -d "$root" || exit 2; '
            'if find "$root" -type l -print -quit | grep -q .; then exit 3; fi; '
            'if find "$root" ! -type f ! -type d -print -quit | grep -q .; then exit 3; fi; '
            'size=$(find "$root" '
            "-path '*/.git' -prune -o -path '*/.gpthub-document' -prune -o "
            "-path '*/artifacts' -prune -o -type f -printf '%s\\n' | "
            "awk '{total += $1} END {print total + 0}'); "
            'case "$size" in ""|*[!0-9]*) exit 4;; esac; '
            'test "$size" -le "$limit" || exit 5'
        )
        code, _ = await _command(
            "docker",
            "exec",
            workspace_ref.container_id,
            "/bin/sh",
            "-c",
            script,
            "document-source",
            project_path,
            str(MAX_SOURCE_BYTES),
            timeout=30.0,
        )
        if code == 5:
            raise CompilerFailure("source_too_large")
        if code:
            raise CompilerFailure("invalid_project")

    async def prepare(
        self,
        workspace_ref: ContainerRef,
        *,
        workspace_root: str,
        project_path: str,
        before_create: Callable[[str], Awaitable[None]] | None = None,
        on_allocated: Callable[[PreparedCompilerJob], Awaitable[None]] | None = None,
    ) -> PreparedCompilerJob:
        await self._validate_source(workspace_ref, project_path)
        job_ref = secrets.token_hex(12)
        container_name = f"gpthub-doc-{job_ref}"
        args = (
            "docker",
            "create",
            "--name",
            container_name,
            "--label",
            "gpthub.document=1",
            "--label",
            "gpthub.document.contract=1",
            "--label",
            f"gpthub.document.workspace_container={workspace_ref.container_id}",
            "--label",
            f"gpthub.document.expires_at={int(time.time() + BUILD_TIMEOUT_SEC + 120)}",
            "--network",
            "none",
            "--memory",
            str(MEMORY_BYTES),
            "--memory-swap",
            str(MEMORY_BYTES),
            "--pids-limit",
            str(PIDS_LIMIT),
            "--cpus",
            str(CPUS),
            "--user",
            "65534:65534",
            "--read-only",
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--tmpfs",
            f"/job:rw,exec,size={MAX_SOURCE_BYTES},mode=1777",
            "--tmpfs",
            # Raster pages and their deterministic tar bundle coexist until publication.
            f"/output:rw,size={MAX_ARTIFACT_BYTES + (MAX_VISUAL_BYTES * 2)},mode=1777",
            "--tmpfs",
            "/tmp:rw,exec,size=268435456,mode=1777",
            "--entrypoint",
            "sleep",
            DOCUMENT_IMAGE,
            "infinity",
        )
        container_id = ""
        project_name = project_path.rstrip("/").rsplit("/", 1)[-1]
        if before_create is not None:
            await before_create(job_ref)

        async def create() -> None:
            nonlocal container_id
            code, out = await _command(*args)
            if code:
                raise CompilerFailure("runtime_unavailable")
            container_id = out.decode("utf-8", "replace").strip()

        creation = asyncio.create_task(create())
        self._creating[job_ref] = creation
        try:
            try:
                await asyncio.shield(creation)
            except asyncio.CancelledError:
                # Docker create can commit after its caller disconnects. Drain
                # the bounded create operation to learn the exact owned ID.
                try:
                    await asyncio.shield(creation)
                    if on_allocated is not None:
                        await on_allocated(PreparedCompilerJob(job_ref, container_id, project_name))
                except Exception:
                    pass
                raise
            self._creating.pop(job_ref, None)
            if on_allocated is not None:
                await on_allocated(PreparedCompilerJob(job_ref, container_id, project_name))
            code, _ = await _command("docker", "start", container_id)
            if code:
                raise CompilerFailure("runtime_unavailable")
            project_parent = project_path.rstrip("/").rsplit("/", 1)[0] or workspace_root
            await _pipe(
                (
                    "docker",
                    "exec",
                    workspace_ref.container_id,
                    "tar",
                    "-C",
                    project_parent,
                    f"--exclude={project_name}/.git",
                    f"--exclude={project_name}/.gpthub-document",
                    f"--exclude={project_name}/artifacts",
                    "-cf",
                    "-",
                    project_name,
                ),
                (
                    "docker",
                    "exec",
                    "-i",
                    container_id,
                    "tar",
                    "-C",
                    "/job",
                    "-xf",
                    "-",
                ),
                timeout=60.0,
            )
        except BaseException:
            self._preparation_cleanup[job_ref] = (workspace_ref, container_id or container_name)
            try:
                if container_id and await self.destroy(container_id):
                    self._preparation_cleanup.pop(job_ref, None)
            except Exception:
                self.cleanup_failures += 1
            if creation.done():
                self._creating.pop(job_ref, None)
                if not creation.cancelled():
                    creation.exception()
            raise
        return PreparedCompilerJob(job_ref, container_id, project_name)

    async def execute(
        self,
        job: PreparedCompilerJob,
        *,
        entrypoint: str,
        engine: str,
        final: bool,
        timeout_sec: float = BUILD_TIMEOUT_SEC,
    ) -> CompilerResult:
        code, _ = await _command(
            "docker",
            "exec",
            job.container_id,
            "python3",
            "/opt/document-runtime/runner.py",
            "--project",
            f"/job/{job.project_name}",
            "--entrypoint",
            entrypoint,
            "--engine",
            engine,
            "--timeout",
            str(min(max(1.0, timeout_sec), BUILD_TIMEOUT_SEC)),
            *(("--publication",) if final else ()),
            timeout=BUILD_TIMEOUT_SEC + 30.0,
        )
        report_code, report_bytes = await _command(
            "docker", "exec", job.container_id, "cat", "/output/report.json", timeout=15.0
        )
        if report_code:
            return CompilerResult("failed", "runtime_unavailable", {})
        try:
            report = json.loads(report_bytes[:262_144])
        except (UnicodeError, ValueError):
            return CompilerResult("failed", "runtime_unavailable", {})
        status = "ready" if code == 0 and report.get("status") == "ready" else "failed"
        failure = "" if status == "ready" else str(report.get("failure_code") or "compile_failed")
        return CompilerResult(status, failure, report)

    async def publish_outputs(
        self,
        job: PreparedCompilerJob,
        workspace_ref: ContainerRef,
        *,
        staging_dir: str,
    ) -> None:
        code, _ = await _command(
            "docker",
            "exec",
            workspace_ref.container_id,
            "/bin/sh",
            "-c",
            f"mkdir -p {shlex.quote(staging_dir)}",
        )
        if code:
            raise CompilerFailure("runtime_unavailable")
        await _pipe(
            (
                "docker",
                "exec",
                job.container_id,
                "tar",
                "-C",
                "/output",
                "-cf",
                "-",
                ".",
            ),
            (
                "docker",
                "exec",
                "-i",
                workspace_ref.container_id,
                "tar",
                "-C",
                staging_dir,
                "-xf",
                "-",
            ),
            timeout=60.0,
        )

    async def artifact_facts(
        self,
        workspace_ref: ContainerRef,
        path: str,
        *,
        max_bytes: int = MAX_ARTIFACT_BYTES,
    ) -> tuple[str, int]:
        code, payload = await _command(
            "docker",
            "exec",
            workspace_ref.container_id,
            "/bin/sh",
            "-c",
            'test -f "$1" && sha256sum "$1" | cut -d\' \' -f1 && wc -c < "$1"',
            "document-artifact",
            path,
            timeout=30.0,
        )
        if code:
            raise CompilerFailure("runtime_unavailable")
        lines = payload.decode("ascii", "ignore").splitlines()
        try:
            digest = lines[0].strip()
            size = int(lines[1].strip())
        except (IndexError, ValueError):
            raise CompilerFailure("artifact_invalid") from None
        if len(digest) != 64 or size < 0:
            raise CompilerFailure("artifact_invalid")
        if size > max_bytes:
            raise CompilerFailure("artifact_too_large")
        return digest, size

    async def artifact_stream(
        self,
        workspace_ref: ContainerRef,
        path: str,
        *,
        max_bytes: int = MAX_ARTIFACT_BYTES,
    ) -> AsyncIterator[bytes]:
        """Yield an artifact without retaining it in the sidecar process."""

        proc = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            workspace_ref.container_id,
            "cat",
            path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert proc.stdout is not None
        seen = 0
        try:
            while chunk := await proc.stdout.read(1024 * 1024):
                seen += len(chunk)
                if seen > max_bytes:
                    raise CompilerFailure("artifact_too_large")
                yield chunk
            if await proc.wait():
                raise CompilerFailure("runtime_unavailable")
        except BaseException:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise

    async def destroy(self, container_id: str) -> bool:
        if not container_id:
            return True
        try:
            code, _ = await _command("docker", "rm", "-f", container_id, timeout=30.0)
            if not code or await container_absent(_command, container_id):
                return True
        except (OSError, CompilerFailure, UnicodeError):
            self.cleanup_failures += 1
            return False
        self.cleanup_failures += 1
        return False

    async def reconcile(self) -> int:
        for job_ref, (workspace_ref, container_id) in tuple(self._preparation_cleanup.items()):
            creation = self._creating.get(job_ref)
            if creation is not None:
                if not creation.done():
                    continue
                self._creating.pop(job_ref, None)
                if not creation.cancelled():
                    creation.exception()
            if container_id == f"gpthub-doc-{job_ref}":
                try:
                    status, data = await _command(
                        "docker", "ps", "-aq", "--no-trunc", "--filter", f"name=^/{container_id}$"
                    )
                    values = data.decode().splitlines()
                    if status or len(values) > 1:
                        continue
                    if not values:
                        # No ID was accepted from create. A negative snapshot
                        # cannot rule out a late daemon commit, so keep the
                        # reservation until an owned allocation is observed.
                        continue
                    container_id = values[0].strip()
                except (OSError, CompilerFailure, UnicodeError):
                    self.cleanup_failures += 1
                    continue
            if await self.cleanup_recovered(container_id, workspace_ref, job_ref):
                self._preparation_cleanup.pop(job_ref, None)
        try:
            code, out = await _command(
                "docker",
                "ps",
                "-aq",
                "--no-trunc",
                "--filter",
                "label=gpthub.document=1",
                timeout=30.0,
            )
        except (OSError, CompilerFailure):
            self.cleanup_failures += 1
            return 0
        if code:
            self.cleanup_failures += 1
            return 0
        removed = 0
        now = time.time()
        for container_id in out.decode().splitlines()[:128]:
            container_id = container_id.strip()
            if not container_id:
                continue
            try:
                observed = await compiler_state(_command, container_id)
                if observed is None:
                    if not await container_absent(_command, container_id):
                        self.cleanup_failures += 1
                    continue
            except (OSError, CompilerFailure, UnicodeError):
                self.cleanup_failures += 1
                continue
            expires_at, running = observed
            if expires_at > now and running:
                continue
            if await self.destroy(container_id):
                removed += 1
        self.reconciled_cleanup += removed
        return removed

    async def resolve_owned_preparation(
        self, name: str, workspace_ref: ContainerRef, build_id: str
    ) -> str | None:
        """Resolve a journaled name without treating negative lookup as settlement."""
        if name != f"gpthub-doc-{build_id}":
            return None
        try:
            code, raw = await _command(
                "docker", "inspect", "--format", "{{json .}}", name, timeout=15.0
            )
            if code:
                return None
            record = json.loads(raw)
            labels = record.get("Config", {}).get("Labels", {}) or {}
            identifier = record.get("Id", "")
            if (
                record.get("Name") != f"/{name}"
                or labels.get("gpthub.document") != "1"
                or labels.get("gpthub.document.contract") != "1"
                or labels.get("gpthub.document.workspace_container") != workspace_ref.container_id
                or not isinstance(identifier, str)
                or len(identifier) != 64
                or any(ch not in "0123456789abcdef" for ch in identifier)
            ):
                return None
            return identifier
        except (OSError, CompilerFailure, ValueError, TypeError, AttributeError):
            self.cleanup_failures += 1
            return None

    async def cleanup_recovered(
        self, container_id: str, workspace_ref: ContainerRef, build_id: str
    ) -> bool:
        """Remove only the exact compiler owned by a recovered interrupted build."""
        if len(container_id) != 64 or any(ch not in "0123456789abcdef" for ch in container_id):
            return False
        try:
            code, raw = await _command(
                "docker", "inspect", "--format", "{{json .}}", container_id, timeout=15.0
            )
            if code:
                # Distinguish proven absence from a Docker outage before clearing
                # the persisted cleanup reference.
                return await container_absent(_command, container_id)
            record = json.loads(raw)
            labels = record.get("Config", {}).get("Labels", {}) or {}
            if (
                labels.get("gpthub.document") != "1"
                or labels.get("gpthub.document.contract") != "1"
                or labels.get("gpthub.document.workspace_container") != workspace_ref.container_id
                or record.get("Name") != f"/gpthub-doc-{build_id}"
            ):
                return False
            preparation = self._preparation_cleanup.get(build_id)
            if (
                preparation is not None
                and preparation[0].container_id == workspace_ref.container_id
            ):
                # Ownership is now proven. Future confirmed absence of this
                # exact allocation may settle cleanup, unlike absence by name
                # before a create response has ever been accepted.
                self._preparation_cleanup[build_id] = (workspace_ref, container_id)
            cleaned = await self.destroy(container_id)
            self.reconciled_cleanup += int(cleaned)
            return cleaned
        except (OSError, CompilerFailure, ValueError, TypeError, AttributeError):
            self.cleanup_failures += 1
            return False

    def health(self) -> dict[str, int]:
        return {
            "compiler_cleanup": self.reconciled_cleanup,
            "compiler_cleanup_failures": self.cleanup_failures,
            "compiler_preparation_pending": self.pending_preparation_cleanup,
        }
