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
from collections.abc import AsyncIterator
from dataclasses import dataclass

from drivers import ContainerRef

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
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if input_bytes is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(input_bytes), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise CompilerFailure("runtime_unavailable") from None
    return proc.returncode or 0, out


async def _pipe(left: tuple[str, ...], right: tuple[str, ...], *, timeout: float) -> None:
    producer = await asyncio.create_subprocess_exec(
        *left, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    assert producer.stdout is not None
    consumer = await asyncio.create_subprocess_exec(
        *right,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert consumer.stdin is not None

    async def forward() -> None:
        try:
            while chunk := await producer.stdout.read(1024 * 1024):
                consumer.stdin.write(chunk)
                await consumer.stdin.drain()
        finally:
            consumer.stdin.close()
            await consumer.stdin.wait_closed()

    try:
        _, producer_code, consumer_code = await asyncio.wait_for(
            asyncio.gather(forward(), producer.wait(), consumer.wait()), timeout=timeout
        )
    except TimeoutError:
        producer.kill()
        consumer.kill()
        await asyncio.gather(producer.wait(), consumer.wait(), return_exceptions=True)
        raise CompilerFailure("runtime_unavailable") from None
    if producer_code or consumer_code:
        raise CompilerFailure("runtime_unavailable")


class DockerDocumentCompiler:
    """Prepare, execute and drain one compiler container."""

    def __init__(self) -> None:
        self.reconciled_cleanup = 0
        self.cleanup_failures = 0

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
        code, out = await _command(*args)
        if code:
            raise CompilerFailure("runtime_unavailable")
        container_id = out.decode("utf-8", "replace").strip()
        try:
            code, _ = await _command("docker", "start", container_id)
            if code:
                raise CompilerFailure("runtime_unavailable")
            project_name = project_path.rstrip("/").rsplit("/", 1)[-1]
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
        except Exception:
            await self.destroy(container_id)
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
        except (OSError, CompilerFailure):
            self.cleanup_failures += 1
            return False
        if code:
            self.cleanup_failures += 1
            return False
        return True

    async def reconcile(self) -> int:
        try:
            code, out = await _command(
                "docker", "ps", "-aq", "--filter", "label=gpthub.document=1", timeout=30.0
            )
        except (OSError, CompilerFailure):
            return 0
        if code:
            return 0
        removed = 0
        now = time.time()
        for container_id in out.decode().splitlines()[:128]:
            container_id = container_id.strip()
            if not container_id:
                continue
            labels_code, labels_raw = await _command(
                "docker",
                "inspect",
                "--format",
                "{{json .Config.Labels}}",
                container_id,
                timeout=15.0,
            )
            state_code, state_raw = await _command(
                "docker",
                "inspect",
                "--format",
                "{{.State.Running}}",
                container_id,
                timeout=15.0,
            )
            try:
                labels = json.loads(labels_raw) if not labels_code else {}
                expires_at = float(labels.get("gpthub.document.expires_at") or 0)
            except (TypeError, ValueError):
                expires_at = 0
            running = not state_code and state_raw.decode().strip().lower() == "true"
            if expires_at > now and running:
                continue
            if await self.destroy(container_id):
                removed += 1
        self.reconciled_cleanup += removed
        return removed

    def health(self) -> dict[str, int]:
        return {
            "compiler_cleanup": self.reconciled_cleanup,
            "compiler_cleanup_failures": self.cleanup_failures,
        }
