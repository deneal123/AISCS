"""Run-scoped document build registry and two-phase publication."""

from __future__ import annotations

import asyncio
import hashlib
import posixpath
import shlex
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from domain.documents import DocumentArtifact, DocumentBuild, DocumentDiagnostic
from domain.files import safe_path
from infrastructure.document_compiler import CompilerFailure, DockerDocumentCompiler

from .build_store import ACTIVE_STATES, BuildManifestStore
from .projects import DocumentProjectError, DocumentProjectService

Revision = Callable[[Any], Awaitable[str]]
VISUAL_DIAGNOSTIC_CODES = frozenset(
    {
        "visual_blank_page",
        "visual_clipping",
        "visual_overlap",
        "visual_readability",
        "visual_table_overflow",
        "visual_image_quality",
        "visual_header_footer",
        "visual_composition",
    }
)
VISUAL_AUDIT_LEASE_SEC = 120


class DocumentBuildManager:
    def __init__(
        self,
        compiler: DockerDocumentCompiler,
        projects: DocumentProjectService,
        revision: Revision,
        *,
        max_jobs: int = 32,
        store: BuildManifestStore | None = None,
    ) -> None:
        self.compiler = compiler
        self.projects = projects
        self.revision = revision
        self.max_jobs = max_jobs
        self.store = store or BuildManifestStore()
        self._builds: dict[str, DocumentBuild] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancel_requested: set[str] = set()
        self._recovered_workspaces: set[str] = set()
        self._lock = asyncio.Lock()
        self.recovered = 0
        self.interrupted = 0
        self.manifest_failures = 0

    async def _persist(self, registry: Any, item: Any, build: DocumentBuild) -> None:
        try:
            async with registry.operation(item):
                await self.store.save(registry, item, build)
        except Exception:
            self.manifest_failures += 1
            raise DocumentProjectError("runtime_unavailable") from None

    async def recover(self, registry: Any, item: Any) -> None:
        """Load one workspace's private manifests exactly once per sidecar process."""

        workspace_id = str(item.workspace_id)
        async with self._lock:
            if workspace_id in self._recovered_workspaces:
                return
            self._recovered_workspaces.add(workspace_id)
        try:
            async with registry.operation(item):
                records = await self.store.load(registry, item)
            recovered: list[DocumentBuild] = []
            for build in records:
                if build.state == "visual_audit":
                    build.state = "visual_pending"
                    build.failure_code = "visual_interrupted"
                    self.interrupted += 1
                    await self._persist(registry, item, build)
                elif build.state in ACTIVE_STATES:
                    build.state = "failed"
                    build.failure_code = "build_interrupted"
                    build.completed_at = time.time()
                    self.interrupted += 1
                    await self._persist(registry, item, build)
                elif build.state in {"visual_pending", "preview_ready", "ready"}:
                    async with registry.operation(item):
                        valid = await self.store.verify_artifacts(registry, item, build)
                    if not valid:
                        build.state = "failed"
                        build.failure_code = "artifact_invalid"
                        build.completed_at = time.time()
                        await self._persist(registry, item, build)
                recovered.append(build)
            async with self._lock:
                for build in recovered:
                    self._builds.setdefault(build.build_id, build)
                self.recovered += len(recovered)
            await self._prune(registry, item)
        except Exception:
            async with self._lock:
                self._recovered_workspaces.discard(workspace_id)
            self.manifest_failures += 1
            raise DocumentProjectError("runtime_unavailable") from None

    async def _prune(self, registry: Any, item: Any) -> None:
        values = tuple(
            build for build in self._builds.values() if build.workspace_id == item.workspace_id
        )
        for build_id in self.store.prune_candidates(values):
            await self.store.delete(registry, item, build_id)
            async with self._lock:
                self._builds.pop(build_id, None)
                self._tasks.pop(build_id, None)

    async def start(
        self,
        registry: Any,
        item: Any,
        *,
        project_path: str,
        expected_revision: str,
        final: bool,
    ) -> DocumentBuild:
        await self.recover(registry, item)
        async with self._lock:
            active = sum(not task.done() for task in self._tasks.values())
            if active >= self.max_jobs:
                raise DocumentProjectError("runtime_unavailable")
        async with registry.operation(item):
            current_revision = await self.revision(item)
            if not expected_revision or current_revision != expected_revision:
                raise DocumentProjectError("revision_conflict")
            raw, profile = await self.projects.manifest(item, project_path)
            source_digest = await self.projects.digest(item, project_path)
            target = safe_path(item.policy.root, project_path)
            prepared = await self.compiler.prepare(
                item.ref,
                workspace_root=item.policy.root,
                project_path=target,
            )
        build = DocumentBuild(
            build_id=prepared.job_ref,
            workspace_id=item.workspace_id,
            project_path=target,
            profile_id=profile.profile_id,
            profile_version=profile.version,
            source_revision=current_revision,
            source_digest=source_digest,
            mode=str(raw.get("mode") or "draft"),
            final=final,
            state="building",
            compiler_ref=prepared.container_id,
        )
        async with self._lock:
            self._builds[build.build_id] = build
        await self._persist(registry, item, build)
        async with self._lock:
            self._tasks[build.build_id] = asyncio.create_task(
                self._execute(registry, item, build, prepared, profile)
            )
        return build

    async def _execute(self, registry, item, build, prepared, profile) -> None:
        try:
            build.state = "building"
            await self._persist(registry, item, build)
            result = await self.compiler.execute(
                prepared,
                entrypoint=profile.entrypoint,
                engine=profile.engine,
                final=build.final,
            )
            if result.status != "ready":
                build.state = "failed"
                build.failure_code = result.failure_code
                build.diagnostics = self._diagnostics(result.report)
                build.completed_at = time.time()
                await self._persist(registry, item, build)
                return
            build.state = "deterministic_audit"
            await self._persist(registry, item, build)
            report = result.report
            async with registry.operation(item):
                current_revision = await self.revision(item)
                current_digest = await self.projects.digest(item, build.project_path)
                if (
                    current_revision != build.source_revision
                    or current_digest != build.source_digest
                ):
                    raise DocumentProjectError("source_changed")
                build.state = "publishing"
                staging = f"{item.policy.root}/.gpthub-document/{build.build_id}"
                await self.compiler.publish_outputs(prepared, item.ref, staging_dir=staging)
                artifact_dir = f"{build.project_path}/artifacts"
                published_dir = f"{artifact_dir}/{build.build_id}"
                filename = f"{profile.profile_id}-{build.build_id[:8]}.pdf"
                target = f"{published_dir}/document.pdf"
                preview_name = f"{profile.profile_id}-{build.build_id[:8]}-preview.png"
                preview_target = f"{published_dir}/preview.png"
                bundle_target = f"{published_dir}/source.zip"
                visual_target = f"{published_dir}/visual-pages.tar"
                bundle_prune = (
                    ""
                    if build.final and profile.source_export != "forbidden"
                    else f"rm -f {shlex.quote(staging + '/source.zip')} && "
                )
                command = (
                    f"mkdir -p {shlex.quote(artifact_dir)} && "
                    f"test -f {shlex.quote(staging + '/document.pdf')} && "
                    f"test ! -e {shlex.quote(published_dir)} && "
                    f"{bundle_prune}"
                    f"mv {shlex.quote(staging)} {shlex.quote(published_dir)} && echo __OK__"
                )
                publication = await registry.exec_raw(item, command, max_output_chars=1024)
                if "__OK__" not in publication.stdout:
                    raise CompilerFailure("runtime_unavailable")
                build.output_revision = await self.revision(item)
            artifact_data = (
                report.get("artifact") if isinstance(report.get("artifact"), dict) else {}
            )
            sha = str(artifact_data.get("sha256") or "")
            size = int(artifact_data.get("size") or 0)
            artifact_id = hashlib.sha256(f"{build.build_id}:pdf:{sha}".encode()).hexdigest()[:24]
            artifacts = [
                DocumentArtifact(
                    artifact_id=artifact_id,
                    role="pdf",
                    filename=filename,
                    mime_type="application/pdf",
                    size=size,
                    sha256=sha,
                    internal_path=target,
                )
            ]
            preview_data = (
                report.get("preview") if isinstance(report.get("preview"), dict) else None
            )
            if preview_data:
                preview_sha = str(preview_data.get("sha256") or "")
                artifacts.append(
                    DocumentArtifact(
                        artifact_id=hashlib.sha256(
                            f"{build.build_id}:thumbnail:{preview_sha}".encode()
                        ).hexdigest()[:24],
                        role="thumbnail",
                        filename=preview_name,
                        mime_type="image/png",
                        size=int(preview_data.get("size") or 0),
                        sha256=preview_sha,
                        internal_path=preview_target,
                    )
                )
            bundle_data = (
                report.get("source_bundle")
                if isinstance(report.get("source_bundle"), dict)
                else None
            )
            if build.final and profile.source_export != "forbidden" and bundle_data:
                bundle_sha = str(bundle_data.get("sha256") or "")
                bundle_name = f"{profile.profile_id}-{build.build_id[:8]}-source.zip"
                artifacts.append(
                    DocumentArtifact(
                        artifact_id=hashlib.sha256(
                            f"{build.build_id}:source:{bundle_sha}".encode()
                        ).hexdigest()[:24],
                        role="source_bundle",
                        filename=bundle_name,
                        mime_type="application/zip",
                        size=int(bundle_data.get("size") or 0),
                        sha256=bundle_sha,
                        internal_path=bundle_target,
                    )
                )
            visual_data = (
                report.get("visual_bundle")
                if isinstance(report.get("visual_bundle"), dict)
                else None
            )
            if build.final and visual_data:
                build.visual_bundle_path = visual_target
                build.visual_bundle_sha256 = str(visual_data.get("sha256") or "")
                build.visual_bundle_size = max(0, int(visual_data.get("size") or 0))
            if build.final and (
                not build.visual_bundle_path
                or len(build.visual_bundle_sha256) != 64
                or build.visual_bundle_size < 1
            ):
                raise CompilerFailure("visual_render_failed")
            build.artifacts = tuple(artifacts)
            build.page_count = int(report.get("page_count") or 0)
            build.page_width_pt = float(report.get("page_width_pt") or 0.0)
            build.page_height_pt = float(report.get("page_height_pt") or 0.0)
            build.diagnostics = self._diagnostics(report)
            build.state = "visual_pending" if build.final else "preview_ready"
            build.failure_code = ""
            if not build.final:
                build.completed_at = time.time()
            await self._persist(registry, item, build)
        except asyncio.CancelledError:
            user_cancelled = build.build_id in self._cancel_requested
            build.state = "cancelled" if user_cancelled else "failed"
            build.failure_code = "build_cancelled" if user_cancelled else "build_interrupted"
            build.completed_at = time.time()
            await self._persist(registry, item, build)
            raise
        except (CompilerFailure, DocumentProjectError) as exc:
            build.state = "failed"
            build.failure_code = exc.code
            build.completed_at = time.time()
            try:
                await self._persist(registry, item, build)
            except DocumentProjectError:
                pass
        except Exception:
            build.state = "failed"
            build.failure_code = "internal"
            build.completed_at = time.time()
            try:
                await self._persist(registry, item, build)
            except DocumentProjectError:
                pass
        finally:
            self._cancel_requested.discard(build.build_id)
            await self.compiler.destroy(prepared.container_id)

    @staticmethod
    def _diagnostics(report: dict[str, object]) -> tuple[DocumentDiagnostic, ...]:
        out: list[DocumentDiagnostic] = []
        raw = report.get("diagnostics")
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity") or "error")
            code = str(item.get("code") or "internal")
            path = posixpath.basename(str(item.get("path") or ""))
            line = item.get("line")
            out.append(
                DocumentDiagnostic(
                    severity=severity if severity in {"info", "warning", "error"} else "error",
                    code=code[:64],
                    relative_path=path,
                    line=int(line) if isinstance(line, int) and line > 0 else None,
                    count=max(1, int(item.get("count") or 1)),
                )
            )
        return tuple(out[:100])

    def get(self, workspace_id: str, build_id: str) -> DocumentBuild | None:
        build = self._builds.get(build_id)
        return build if build is not None and build.workspace_id == workspace_id else None

    async def find(self, registry: Any, item: Any, build_id: str) -> DocumentBuild | None:
        await self.recover(registry, item)
        return self.get(item.workspace_id, build_id)

    async def latest_for_project(
        self, registry: Any, item: Any, project_path: str
    ) -> DocumentBuild | None:
        """Return the newest durable build for reload recovery of one project."""

        await self.recover(registry, item)
        target = safe_path(item.policy.root, project_path)
        candidates = (
            build
            for build in self._builds.values()
            if build.workspace_id == item.workspace_id and build.project_path == target
        )
        return max(candidates, key=lambda build: build.created_at, default=None)

    async def cancel(
        self, registry: Any, item: Any, workspace_id: str, build_id: str
    ) -> DocumentBuild | None:
        build = await self.find(registry, item, build_id)
        if build is None:
            return None
        task = self._tasks.get(build_id)
        if task is not None and not task.done():
            self._cancel_requested.add(build_id)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        elif not build.terminal:
            build.state = "cancelled"
            build.failure_code = "build_cancelled"
            build.completed_at = time.time()
            await self._persist(registry, item, build)
        return build

    async def artifact_stream(
        self, registry: Any, item: Any, build_id: str, artifact_id: str
    ) -> tuple[DocumentArtifact, AsyncIterator[bytes]] | None:
        build = await self.find(registry, item, build_id)
        if build is None or build.state not in {
            "preview_ready",
            "visual_pending",
            "visual_audit",
            "ready",
        }:
            return None
        artifact = next(
            (entry for entry in build.artifacts if entry.artifact_id == artifact_id), None
        )
        if artifact is None:
            return None
        digest, size = await self.compiler.artifact_facts(item.ref, artifact.internal_path)
        if digest != artifact.sha256 or size != artifact.size:
            raise CompilerFailure("artifact_invalid")
        return artifact, self.compiler.artifact_stream(
            item.ref, artifact.internal_path, max_bytes=artifact.size
        )

    async def claim_visual_audit(self, registry: Any, item: Any, build_id: str) -> DocumentBuild:
        build = await self.find(registry, item, build_id)
        if build is None:
            raise DocumentProjectError("build_missing")
        async with self._lock:
            claim_expired = (
                build.state == "visual_audit"
                and build.visual_audit_claimed_at is not None
                and time.time() - build.visual_audit_claimed_at >= VISUAL_AUDIT_LEASE_SEC
            )
            if build.state == "visual_audit" and not claim_expired:
                raise DocumentProjectError("audit_busy")
            if build.state not in {"visual_pending", "visual_audit"} or not build.final:
                raise DocumentProjectError("audit_unavailable")
            build.state = "visual_audit"
            build.failure_code = ""
            build.visual_audit_claimed_at = time.time()
        await self._persist(registry, item, build)
        return build

    async def visual_bundle_stream(
        self, registry: Any, item: Any, build_id: str
    ) -> tuple[dict[str, object], AsyncIterator[bytes]]:
        build = await self.find(registry, item, build_id)
        if (
            build is None
            or build.state not in {"visual_pending", "visual_audit"}
            or not build.visual_bundle_path
        ):
            raise DocumentProjectError("audit_unavailable")
        digest, size = await self.compiler.artifact_facts(
            item.ref,
            build.visual_bundle_path,
            max_bytes=build.visual_bundle_size,
        )
        if digest != build.visual_bundle_sha256 or size != build.visual_bundle_size:
            raise DocumentProjectError("artifact_invalid")
        pdf = next((artifact for artifact in build.artifacts if artifact.role == "pdf"), None)
        if pdf is None:
            raise DocumentProjectError("artifact_invalid")
        metadata = {
            "build_id": build.build_id,
            "source_digest": build.source_digest,
            "artifact_sha256": pdf.sha256,
            "bundle_sha256": digest,
            "bundle_size": size,
            "page_count": build.page_count,
            "profile_id": build.profile_id,
            "profile_version": build.profile_version,
        }
        return metadata, self.compiler.artifact_stream(
            item.ref, build.visual_bundle_path, max_bytes=build.visual_bundle_size
        )

    async def visual_page_stream(
        self,
        registry: Any,
        item: Any,
        build_id: str,
        page: int,
    ) -> tuple[int, str, AsyncIterator[bytes]]:
        build = await self.find(registry, item, build_id)
        if (
            build is None
            or build.state not in {"visual_pending", "visual_audit"}
            or page < 1
            or page > build.page_count
        ):
            raise DocumentProjectError("audit_unavailable")
        page_path = posixpath.join(
            posixpath.dirname(build.visual_bundle_path),
            "visual-pages",
            f"page-{page}.png",
        )
        digest, size = await self.compiler.artifact_facts(
            item.ref, page_path, max_bytes=16 * 1024 * 1024
        )
        return (
            size,
            digest,
            self.compiler.artifact_stream(item.ref, page_path, max_bytes=16 * 1024 * 1024),
        )

    async def complete_visual_audit(
        self,
        registry: Any,
        item: Any,
        build_id: str,
        *,
        source_digest: str,
        artifact_sha256: str,
        passed: bool,
        retryable: bool,
        audit_version: int,
        diagnostics: list[dict[str, object]],
    ) -> DocumentBuild:
        build = await self.find(registry, item, build_id)
        if build is None or build.state not in {"visual_pending", "visual_audit"}:
            raise DocumentProjectError("audit_unavailable")
        pdf = next((artifact for artifact in build.artifacts if artifact.role == "pdf"), None)
        if pdf is None or source_digest != build.source_digest or artifact_sha256 != pdf.sha256:
            raise DocumentProjectError("source_changed")
        visual = tuple(
            DocumentDiagnostic(
                severity="error",
                code=str(entry.get("code") or "")[:64],
                line=(int(entry["page"]) if isinstance(entry.get("page"), int) else None),
                count=max(1, int(entry.get("count") or 1)),
            )
            for entry in diagnostics[:100]
            if isinstance(entry, dict) and str(entry.get("code") or "") in VISUAL_DIAGNOSTIC_CODES
        )
        build.visual_audit_version = max(1, int(audit_version or 1))
        build.visual_audit_claimed_at = None
        if passed and not visual:
            build.state = "ready"
            build.failure_code = ""
            build.completed_at = time.time()
        elif retryable:
            build.state = "visual_pending"
            build.failure_code = "visual_unavailable"
        else:
            build.state = "failed"
            build.failure_code = "visual_audit_failed"
            build.completed_at = time.time()
            build.diagnostics = (*build.diagnostics, *visual)[:100]
        await self._persist(registry, item, build)
        return build

    def health(self) -> dict[str, int]:
        values = tuple(self._builds.values())
        return {
            "active": sum(
                item.state
                in {
                    "queued",
                    "preparing",
                    "building",
                    "deterministic_audit",
                    "visual_audit",
                    "publishing",
                }
                for item in values
            ),
            "ready": sum(item.state == "ready" for item in values),
            "failed": sum(item.state == "failed" for item in values),
            "visual_pending": sum(item.state == "visual_pending" for item in values),
            "recovered": self.recovered,
            "interrupted": self.interrupted,
            "manifest_failures": self.manifest_failures,
            **self.compiler.health(),
        }

    async def reconcile_registry(self, registry: Any) -> None:
        for item in await registry.active_workspaces():
            try:
                await self.recover(registry, item)
            except DocumentProjectError:
                continue
        await self.compiler.reconcile()

    async def reconcile_forever(self, registry: Any, interval_sec: float = 60.0) -> None:
        while True:
            await asyncio.sleep(interval_sec)
            await self.reconcile_registry(registry)
