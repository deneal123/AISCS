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
from domain.documents.source_identity import diagnostic_block
from domain.files import safe_path
from infrastructure.document_compiler import CompilerFailure, DockerDocumentCompiler

from .admission import BuildAdmission
from .artifact_integrity import verify_staged_artifacts
from .build_operations import claim_operation, existing_operation
from .build_preparation import prepare_build
from .build_store import ACTIVE_STATES, MAX_COMPLETED_PER_WORKSPACE, BuildManifestStore
from .projects import DocumentProjectError, DocumentProjectService
from .registry_retention import evict_retired_builds
from .visual_transitions import VISUAL_AUDIT_LEASE_SEC as VISUAL_AUDIT_LEASE_SEC
from .visual_transitions import VISUAL_DIAGNOSTIC_CODES as VISUAL_DIAGNOSTIC_CODES
from .visual_transitions import cancel_recovered, claim_visual, complete_visual, resolve_observed

Revision = Callable[[Any], Awaitable[str]]


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
        self._pending_recovery: set[str] = set()
        self._recovery_locks: dict[str, asyncio.Lock] = {}
        self._registry_recovery_lock = asyncio.Lock()
        self._lock = asyncio.Lock()
        self._workspace_starts: dict[str, asyncio.Lock] = {}
        self._admission = BuildAdmission(
            max_jobs,
            self._occupied_compiler_slots,
            observed=self._observed_compiler_slots
            if callable(getattr(compiler, "inventory_refs", None))
            else None,
        )
        self.recovered = 0
        self.interrupted = 0
        self.manifest_failures = 0
        self.reconciliation_failures = 0
        self._reconciliation_unavailable = False

    async def _persist(self, registry: Any, item: Any, build: DocumentBuild) -> None:
        try:
            async with registry.operation(item):
                await self.store.save(registry, item, build)
        except Exception:
            self.manifest_failures += 1
            raise DocumentProjectError("runtime_unavailable") from None

    async def _provenance(self, item: Any, project_path: str) -> dict[str, str]:
        resolver = getattr(self.projects, "block_provenance", None)
        return await resolver(item, project_path) if callable(resolver) else {}

    async def recover(self, registry: Any, item: Any) -> None:
        """Load one workspace's private manifests exactly once per sidecar process."""

        lock = self._recovery_locks.setdefault(str(item.workspace_id), asyncio.Lock())
        async with lock:
            # Build IDs are process-global: validate and register inventories
            # atomically across workspaces, not just within one workspace.
            async with self._registry_recovery_lock:
                await self._recover_workspace(registry, item)

    async def _recover_workspace(self, registry: Any, item: Any) -> None:

        workspace_id = str(item.workspace_id)
        async with self._lock:
            if workspace_id in self._recovered_workspaces:
                return
            self._pending_recovery.add(workspace_id)
        try:
            async with registry.operation(item):
                records = await self.store.load(registry, item)
            async with self._lock:
                for build in records:
                    existing = self._builds.get(build.build_id)
                    if existing is not None and existing.workspace_id != workspace_id:
                        raise DocumentProjectError("runtime_unavailable")
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
                await self._cleanup_interrupted_compiler(registry, item, build)
                recovered.append(build)
            async with self._lock:
                for build in recovered:
                    self._builds.setdefault(build.build_id, build)
            await self._prune(registry, item)
            async with self._lock:
                self._recovered_workspaces.add(workspace_id)
                self._pending_recovery.discard(workspace_id)
                self.recovered += len(recovered)
        except Exception:
            async with self._lock:
                self._recovered_workspaces.discard(workspace_id)
            self.manifest_failures += 1
            raise DocumentProjectError("runtime_unavailable") from None

    async def _prune(self, registry: Any, item: Any, *, reserved: int = 0) -> None:
        values = tuple(
            build for build in self._builds.values() if build.workspace_id == item.workspace_id
        )
        try:
            async with registry.operation(item):
                for build_id in self.store.prune_candidates(values, reserved=reserved):
                    task = self._tasks.get(build_id)
                    if task is not None and not task.done():
                        continue
                    await self.store.delete(registry, item, build_id)
                    async with self._lock:
                        self._builds.pop(build_id, None)
                        self._tasks.pop(build_id, None)
        except Exception:
            self.manifest_failures += 1
            raise DocumentProjectError("runtime_unavailable") from None

    async def start(
        self,
        registry: Any,
        item: Any,
        *,
        project_path: str,
        expected_revision: str,
        final: bool,
        operation_id: str | None = None,
    ) -> DocumentBuild:
        await self.recover(registry, item)
        if operation_id is not None:
            try:
                existing = existing_operation(
                    self,
                    item,
                    operation_id=operation_id,
                    project_path=project_path,
                    expected_revision=expected_revision,
                    final=final,
                )
            except ValueError:
                raise DocumentProjectError("invalid_project") from None
            if existing is not None:
                return existing
        if self._pending_recovery or self._reconciliation_unavailable:
            raise DocumentProjectError("runtime_unavailable")
        async with self._admission.reserve():
            workspace_id = str(item.workspace_id)
            lock = self._workspace_starts.setdefault(workspace_id, asyncio.Lock())
            async with lock:
                if operation_id is not None:
                    existing = existing_operation(
                        self,
                        item,
                        operation_id=operation_id,
                        project_path=project_path,
                        expected_revision=expected_revision,
                        final=final,
                    )
                    if existing is not None:
                        return existing
                    claimed = await claim_operation(
                        registry,
                        item,
                        operation_id=operation_id,
                        project_path=project_path,
                        expected_revision=expected_revision,
                        final=final,
                    )
                    if not claimed:
                        # There may have been a crash before the first manifest.
                        # Absence of that manifest never authorizes another create.
                        raise DocumentProjectError("runtime_unavailable")
                await self._reserve_manifest(registry, item)
                return await self._start_reserved(
                    registry,
                    item,
                    project_path=project_path,
                    expected_revision=expected_revision,
                    final=final,
                    operation_id=operation_id,
                )

    async def _reserve_manifest(self, registry: Any, item: Any) -> None:
        active = sum(
            build.workspace_id == item.workspace_id and build.state in ACTIVE_STATES
            for build in self._builds.values()
        )
        # Reserve a terminal manifest for every active build and the new one.
        # If all remaining records are protected, refuse before allocating a
        # compiler instead of erasing cleanup or publication intent.
        await self._prune(registry, item, reserved=active + 1)
        count = sum(build.workspace_id == item.workspace_id for build in self._builds.values())
        if count >= MAX_COMPLETED_PER_WORKSPACE:
            raise DocumentProjectError("runtime_unavailable")

    def _occupied_compiler_slots(self) -> int:
        references = {key for key, build in self._builds.items() if build.compiler_ref}
        active = {key for key, task in self._tasks.items() if not task.done()}
        return len(references | active) + getattr(self.compiler, "pending_preparation_cleanup", 0)

    async def _observed_compiler_slots(self) -> int:
        references = set(await self.compiler.inventory_refs())
        references.update(
            build.compiler_ref for build in self._builds.values() if build.compiler_ref
        )
        references.update(getattr(self.compiler, "preparation_cleanup_refs", ()))
        # Retain a task's slot while its final manifest clears a reference, even
        # if Docker has already confirmed that the physical container is gone.
        unreferenced_tasks = sum(
            not task.done() and not self._builds[key].compiler_ref
            for key, task in self._tasks.items()
            if key in self._builds
        )
        return len(references) + unreferenced_tasks

    async def _start_reserved(
        self,
        registry: Any,
        item: Any,
        *,
        project_path: str,
        expected_revision: str,
        final: bool,
        operation_id: str | None = None,
    ) -> DocumentBuild:
        build, prepared, profile = await prepare_build(
            self,
            registry,
            item,
            project_path=project_path,
            expected_revision=expected_revision,
            final=final,
            operation_id=operation_id,
        )
        try:
            await self._persist(registry, item, build)
            async with self._lock:
                self._tasks[build.build_id] = asyncio.create_task(
                    self._execute(registry, item, build, prepared, profile)
                )
        except BaseException as error:
            # Preparation has already allocated a container. No execution task
            # owns it yet, so retain a terminal cleanup intent on every failed
            # handoff, including cancellation. Never release capacity on an
            # unconfirmed destroy or failed manifest update.
            build.state = "cancelled" if isinstance(error, asyncio.CancelledError) else "failed"
            build.failure_code = (
                "cancelled" if build.state == "cancelled" else "runtime_unavailable"
            )
            build.completed_at = time.time()
            try:
                await self._persist(registry, item, build)
            except Exception:
                pass
            try:
                await self._cleanup_interrupted_compiler(registry, item, build)
            except Exception:
                pass
            raise
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
                provenance = await self._provenance(item, build.project_path)
                diagnostics = self._diagnostics(result.report, provenance)
                # ``state`` is the externally observed terminal latch.  Publish
                # it only after every field in the terminal snapshot is ready;
                # otherwise a concurrent status read can see ``failed`` with no
                # diagnostics and trigger a wrong repair path.
                build.failure_code = result.failure_code
                build.diagnostics = diagnostics
                build.completed_at = time.time()
                build.state = "failed"
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
                await verify_staged_artifacts(self.compiler, item.ref, staging, report)
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
            page_blocks: dict[int, list[str]] = {}
            raw_block_pages = report.get("block_pages")
            for entry in raw_block_pages if isinstance(raw_block_pages, list) else []:
                if not isinstance(entry, dict):
                    continue
                page = entry.get("page")
                block_id = str(entry.get("block_id") or "")
                if (
                    isinstance(page, int)
                    and 1 <= page <= build.page_count
                    and 3 <= len(block_id) <= 64
                ):
                    page_blocks.setdefault(page, []).append(block_id)
            build.page_blocks = {
                page: tuple(dict.fromkeys(blocks)) for page, blocks in page_blocks.items()
            }
            provenance = await self._provenance(item, build.project_path)
            build.diagnostics = self._diagnostics(report, provenance)
            build.failure_code = ""
            if not build.final:
                build.completed_at = time.time()
            build.state = "visual_pending" if build.final else "preview_ready"
            await self._persist(registry, item, build)
        except asyncio.CancelledError:
            user_cancelled = build.build_id in self._cancel_requested
            build.failure_code = "build_cancelled" if user_cancelled else "build_interrupted"
            build.completed_at = time.time()
            build.state = "cancelled" if user_cancelled else "failed"
            await self._persist(registry, item, build)
            raise
        except (CompilerFailure, DocumentProjectError) as exc:
            build.failure_code = exc.code
            build.completed_at = time.time()
            build.state = "failed"
            try:
                await self._persist(registry, item, build)
            except DocumentProjectError:
                pass
        except Exception:
            build.failure_code = "internal"
            build.completed_at = time.time()
            build.state = "failed"
            try:
                await self._persist(registry, item, build)
            except DocumentProjectError:
                pass
        finally:
            self._cancel_requested.discard(build.build_id)
            if await self.compiler.destroy(prepared.container_id):
                try:
                    await self._clear_compiler_reference(registry, item, build)
                except DocumentProjectError:
                    pass

    @staticmethod
    def _diagnostics(
        report: dict[str, object], provenance: dict[str, str] | None = None
    ) -> tuple[DocumentDiagnostic, ...]:
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
                    block_id=diagnostic_block(item, provenance or {}),
                )
            )
        return tuple(out[:100])

    def get(self, workspace_id: str, build_id: str) -> DocumentBuild | None:
        build = self._builds.get(build_id)
        return build if build is not None and build.workspace_id == workspace_id else None

    async def find(self, registry: Any, item: Any, build_id: str) -> DocumentBuild | None:
        await self.recover(registry, item)
        build = self.get(item.workspace_id, build_id)
        if build is not None:
            await resolve_observed(self, registry, item, build)
        return build

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
        build = max(candidates, key=lambda build: build.created_at, default=None)
        if build is not None:
            await resolve_observed(self, registry, item, build)
        return build

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
        else:
            await cancel_recovered(self, registry, item, build)
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
        return await claim_visual(self, registry, item, build)

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
            "block_pages": [
                {"page": page, "block_ids": list(block_ids)}
                for page, block_ids in sorted(build.page_blocks.items())
            ],
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
        if build is None:
            raise DocumentProjectError("audit_unavailable")
        return await complete_visual(
            self,
            registry,
            item,
            build,
            source_digest=source_digest,
            artifact_sha256=artifact_sha256,
            passed=passed,
            retryable=retryable,
            audit_version=audit_version,
            diagnostics=diagnostics,
        )

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
            "recovery_pending": len(self._pending_recovery),
            "reconciliation_failures": self.reconciliation_failures,
            "reconciliation_unavailable": self._reconciliation_unavailable,
            **self.compiler.health(),
        }

    async def _clear_compiler_reference(self, registry, item, build) -> None:
        previous = build.compiler_ref
        build.compiler_ref = ""
        try:
            await self._persist(registry, item, build)
        except BaseException:
            build.compiler_ref = previous
            raise

    async def _cleanup_interrupted_compiler(self, registry, item, build) -> None:
        """Retry retained cleanup for every outcome after compilation has stopped."""
        if (
            build.state
            not in {
                "failed",
                "cancelled",
                "preview_ready",
                "visual_pending",
                "visual_audit",
                "ready",
            }
            or not build.compiler_ref
        ):
            return
        task = self._tasks.get(build.build_id)
        if task is not None and not task.done():
            return
        if build.compiler_ref == f"gpthub-doc-{build.build_id}":
            resolved = await self.compiler.resolve_owned_preparation(
                build.compiler_ref, item.ref, build.build_id
            )
            if not resolved:
                return
            previous = build.compiler_ref
            build.compiler_ref = resolved
            try:
                await self._persist(registry, item, build)
            except BaseException:
                build.compiler_ref = previous
                raise
        if await self.compiler.cleanup_recovered(build.compiler_ref, item.ref, build.build_id):
            await self._clear_compiler_reference(registry, item, build)

    async def reconcile_registry(self, registry: Any) -> None:
        try:
            await self._reconcile_registry(registry)
        except Exception:
            # Maintenance must survive transient Docker/registry failures. Keep
            # admission closed until an entire subsequent cycle succeeds; never
            # disclose exception bodies or interpret an outage as empty state.
            self.reconciliation_failures += 1
            self._reconciliation_unavailable = True
        else:
            self._reconciliation_unavailable = False

    async def _reconcile_registry(self, registry: Any) -> None:
        workspaces = await registry.active_workspaces()
        active_ids = {str(item.workspace_id) for item in workspaces}
        self._pending_recovery.intersection_update(active_ids)
        self._pending_recovery.update(active_ids - self._recovered_workspaces)
        for item in workspaces:
            try:
                await self.recover(registry, item)
                for build in tuple(self._builds.values()):
                    if build.workspace_id == item.workspace_id:
                        await resolve_observed(self, registry, item, build)
                        await self._cleanup_interrupted_compiler(registry, item, build)
            except DocumentProjectError:
                continue
        await self.compiler.reconcile()

        # Discovery/cleanup awaits can admit a new workspace. Recheck before
        # eviction; an outage at either inventory leaves all obligations intact.
        async with self._lock:
            current = await registry.active_workspaces()
            retained = active_ids | {str(item.workspace_id) for item in current}
            retained.update(key for key, lock in self._workspace_starts.items() if lock.locked())
            retained.update(key for key, lock in self._recovery_locks.items() if lock.locked())
            evict_retired_builds(
                self._builds,
                self._tasks,
                self._cancel_requested,
                self._recovered_workspaces,
                retained,
            )

    async def reconcile_forever(self, registry: Any, interval_sec: float = 60.0) -> None:
        while True:
            await asyncio.sleep(interval_sec)
            await self.reconcile_registry(registry)
