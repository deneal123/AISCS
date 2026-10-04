"""Persist allocation intent before crossing the Docker create boundary."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from domain.documents import DocumentBuild
from domain.files import safe_path

from .projects import DocumentProjectError


async def prepare_build(
    manager: Any,
    registry: Any,
    item: Any,
    *,
    project_path: str,
    expected_revision: str,
    final: bool,
) -> tuple[Any, Any, Any]:
    build = None
    create_permitted = False
    try:
        async with registry.operation(item):
            revision = await manager.revision(item)
            if not expected_revision or revision != expected_revision:
                raise DocumentProjectError("revision_conflict")
            raw, profile = await manager.projects.manifest(item, project_path)
            authoring = getattr(manager.projects, "authoring", None)
            version, draft_digest = (
                await authoring(item, project_path) if callable(authoring) else (0, "")
            )
            digest = await manager.projects.digest(item, project_path)
            target = safe_path(item.policy.root, project_path)

            async def save_intent() -> None:
                try:
                    await manager.store.save(registry, item, build)
                except Exception:
                    manager.manifest_failures += 1
                    raise DocumentProjectError("runtime_unavailable") from None

            async def before_create(job_ref: str) -> None:
                nonlocal build, create_permitted
                build = DocumentBuild(
                    build_id=job_ref,
                    workspace_id=item.workspace_id,
                    project_path=target,
                    profile_id=profile.profile_id,
                    profile_version=profile.version,
                    source_revision=revision,
                    source_digest=digest,
                    authoring_version=version,
                    draft_digest=draft_digest,
                    mode=str(raw.get("mode") or "draft"),
                    final=final,
                    state="preparing",
                    compiler_ref=f"gpthub-doc-{job_ref}",
                )
                manager._builds[job_ref] = build
                # The operation guard is already held: do not reenter _persist.
                await save_intent()
                create_permitted = True

            async def on_allocated(prepared: Any) -> None:
                build.compiler_ref = prepared.container_id
                await save_intent()

            prepared = await manager.compiler.prepare(
                item.ref,
                workspace_root=item.policy.root,
                project_path=target,
                before_create=before_create,
                on_allocated=on_allocated,
            )
            if build is None or not create_permitted:
                # Production compilers must honor the journaling contract.
                await manager.compiler.destroy(prepared.container_id)
                raise DocumentProjectError("runtime_unavailable")
            build.state = "building"
        return build, prepared, profile
    except BaseException as error:
        if build is not None:
            build.state = "cancelled" if isinstance(error, asyncio.CancelledError) else "failed"
            build.failure_code = (
                "cancelled" if build.state == "cancelled" else "runtime_unavailable"
            )
            build.completed_at = time.time()
            if not create_permitted:
                # The driver has not started create, even if the manifest write
                # committed but its acknowledgement was lost.
                build.compiler_ref = ""
            try:
                await manager._persist(registry, item, build)
                await manager._cleanup_interrupted_compiler(registry, item, build)
            except Exception:
                pass
        raise
