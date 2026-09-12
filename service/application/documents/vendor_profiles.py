"""Activate installed vendor v2 overlays as immutable project-local profiles."""

from __future__ import annotations

import io
import json
import posixpath
import secrets
import shlex
import tarfile
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from domain.files import safe_path

from .projects import DocumentProjectService, scaffold_archive
from .vendor_overlays import DocumentVendorOverlayService, VendorOverlayError

RunCommand = Callable[..., Awaitable[Any]]
Snapshot = Callable[[Any, str], Awaitable[Any]]
Revision = Callable[[Any], Awaitable[str]]


class Compiler(Protocol):
    async def prepare(
        self, workspace_ref: Any, *, workspace_root: str, project_path: str
    ) -> Any: ...

    async def execute(self, job: Any, *, entrypoint: str, engine: str, final: bool) -> Any: ...

    async def destroy(self, container_id: str) -> bool: ...


def _clone_archive(base: bytes, effective: dict[str, object]) -> bytes:
    """Append a private effective-profile contract to a trusted scaffold archive."""

    output = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(base), mode="r:") as source:
        with tarfile.open(fileobj=output, mode="w") as target:
            for member in source.getmembers():
                payload = source.extractfile(member) if member.isfile() else None
                target.addfile(member, payload)
            body = json.dumps(effective, sort_keys=True, separators=(",", ":")).encode()
            info = tarfile.TarInfo(".gpthub-effective-profile.json")
            info.size = len(body)
            info.mode = 0o644
            info.mtime = 1_704_067_200
            target.addfile(info, io.BytesIO(body))
    return output.getvalue()


class DocumentVendorProfileService:
    """Clone, probe and publish a v2 overlay without mutating its source project."""

    def __init__(
        self,
        run_command: RunCommand,
        snapshot: Snapshot,
        revision: Revision,
        projects: DocumentProjectService,
        vendors: DocumentVendorOverlayService,
        compiler: Compiler,
    ) -> None:
        self._run = run_command
        self._snapshot = snapshot
        self._revision = revision
        self._projects = projects
        self._vendors = vendors
        self._compiler = compiler

    async def _cleanup(self, registry: Any, item: Any, stage: str) -> None:
        async with registry.operation(item):
            await self._run(item, f"rm -rf {shlex.quote(stage)}")

    async def activate(
        self,
        registry: Any,
        item: Any,
        *,
        path: str,
        package_id: str,
        target_path: str,
        expected_revision: str,
    ) -> dict[str, object]:
        source = safe_path(item.policy.root, path)
        target = safe_path(item.policy.root, target_path)
        source_relative = posixpath.relpath(source, item.policy.root)
        target_relative = posixpath.relpath(target, item.policy.root)
        if target_relative in {"", "."} or target_relative.startswith("../"):
            raise VendorOverlayError("vendor_profile_invalid")
        token = secrets.token_hex(8)
        stage = safe_path(item.policy.root, f".gpthub-document/vendor-profile-{token}")

        async with registry.operation(item):
            if await self._revision(item) != expected_revision:
                raise VendorOverlayError("revision_conflict")
            raw, profile = await self._projects.manifest(item, path)
            declaration = await self._vendors.profile(item, path, package_id)
            if declaration.paper != profile.paper or declaration.orientation != profile.orientation:
                raise VendorOverlayError("vendor_profile_invalid")
            if profile.max_pages and (
                declaration.max_pages is None or declaration.max_pages > profile.max_pages
            ):
                raise VendorOverlayError("vendor_profile_invalid")
            same_contract = declaration.content_contract == profile.content_contract
            effective = {
                "schema_version": 1,
                "base_profile_id": profile.profile_id,
                "base_profile_version": profile.version,
                "vendor_package_id": package_id,
                "documentclass": declaration.documentclass,
                "bibliography_style": declaration.bibliography_style,
                "content_contract": declaration.content_contract,
                "paper": declaration.paper,
                "orientation": declaration.orientation,
                "max_pages": declaration.max_pages or 0,
                "required_sections": list(declaration.required_sections),
                "export_allowed": False,
            }
            archive = _clone_archive(
                scaffold_archive(
                    profile,
                    mode=str(raw.get("mode") or "draft"),
                    locale=str(raw.get("locale") or profile.locale),
                ),
                effective,
            )
            vendor_source = safe_path(item.policy.root, f"{path}/vendor/{package_id}")
            template = safe_path(vendor_source, declaration.template_entrypoint)
            content_names = "figures bibliography" + (" content" if same_contract else "")
            migration = ""
            if not same_contract:
                migration = (
                    f"mkdir -p {shlex.quote(stage + '/migration/source')} && "
                    f"(cd {shlex.quote(source)} && "
                    "find . -type d \\( -name .git -o -name .gpthub-document "
                    "-o -name artifacts -o -name vendor \\) -prune -o "
                    "-type f -name '*.tex' -print0 | tar --null -T - -cf - 2>/dev/null) | "
                    f"tar -C {shlex.quote(stage + '/migration/source')} -xf - 2>/dev/null; "
                )
            command = (
                f"if [ -e {shlex.quote(target)} ]; then echo __EXISTS__; exit 0; fi; "
                f"rm -rf {shlex.quote(stage)} && mkdir -p {shlex.quote(stage)} && "
                f"tar -C {shlex.quote(stage)} -xf - || "
                f"{{ rm -rf {shlex.quote(stage)}; echo __FAILED__; exit 0; }}; "
                f"mkdir -p {shlex.quote(stage + '/vendor')} && "
                f"cp -a {shlex.quote(vendor_source)} {shlex.quote(stage + '/vendor/')}; "
                f"(cd {shlex.quote(source)} && find {content_names} -type f -print0 "
                "2>/dev/null | tar --null -T - -cf - 2>/dev/null) | "
                f"tar -C {shlex.quote(stage)} -xf - 2>/dev/null; "
                f"{migration}cp {shlex.quote(template)} {shlex.quote(stage + '/main.tex')} && "
                "echo __STAGED__"
            )
            result = await self._run(item, command, stdin_payload=archive)
            if "__EXISTS__" in str(result.stdout or ""):
                raise VendorOverlayError("vendor_collision")
            if "__STAGED__" not in str(result.stdout or ""):
                raise VendorOverlayError("vendor_profile_invalid")

        prepared = None
        try:
            prepared = await self._compiler.prepare(
                item.ref,
                workspace_root=item.policy.root,
                project_path=stage,
            )
            probe = await self._compiler.execute(
                prepared,
                entrypoint="main.tex",
                engine=profile.engine,
                final=False,
            )
            if probe.status != "ready":
                raise VendorOverlayError("vendor_profile_invalid")
        except VendorOverlayError:
            await self._cleanup(registry, item, stage)
            raise
        except Exception as exc:
            await self._cleanup(registry, item, stage)
            raise VendorOverlayError("vendor_profile_invalid") from exc
        finally:
            if prepared is not None:
                await self._compiler.destroy(prepared.container_id)

        async with registry.operation(item):
            if await self._revision(item) != expected_revision:
                await self._run(item, f"rm -rf {shlex.quote(stage)}")
                raise VendorOverlayError("revision_conflict")
            command = (
                f"if [ -e {shlex.quote(target)} ]; then echo __EXISTS__; "
                f"rm -rf {shlex.quote(stage)}; exit 0; fi; "
                f"mkdir -p {shlex.quote(posixpath.dirname(target))} && "
                f"mv {shlex.quote(stage)} {shlex.quote(target)} && echo __OK__"
            )
            result = await self._run(item, command)
            if "__EXISTS__" in str(result.stdout or ""):
                raise VendorOverlayError("vendor_collision")
            if "__OK__" not in str(result.stdout or ""):
                raise VendorOverlayError("vendor_profile_invalid")
            try:
                snapshot = await self._snapshot(item, "document_profile")
            except Exception as exc:
                await self._run(item, f"rm -rf {shlex.quote(target)}")
                raise VendorOverlayError("vendor_profile_invalid") from exc
            if isinstance(snapshot, dict) and not snapshot.get("committed"):
                if str(snapshot.get("reason") or "") != "no_changes":
                    await self._run(item, f"rm -rf {shlex.quote(target)}")
                    raise VendorOverlayError("vendor_profile_invalid")
            revision = str(snapshot.get("revision") or "") if isinstance(snapshot, dict) else ""
            if not revision:
                try:
                    revision = await self._revision(item)
                except Exception as exc:
                    await self._run(item, f"rm -rf {shlex.quote(target)}")
                    raise VendorOverlayError("vendor_profile_invalid") from exc
            if not revision:
                await self._run(item, f"rm -rf {shlex.quote(target)}")
                raise VendorOverlayError("vendor_profile_invalid")
        return {
            "outcome": "cloned",
            "path": target_relative,
            "source_path": source_relative,
            "revision": revision,
            "revision_changed": bool(snapshot.get("committed", True))
            if isinstance(snapshot, dict)
            else True,
            "content_status": "copied" if same_contract else "content_migration_required",
            "effective_profile": {
                "base_profile_id": profile.profile_id,
                "vendor_package_id": package_id,
                "content_contract": declaration.content_contract,
                "paper": declaration.paper,
                "orientation": declaration.orientation,
                "max_pages": declaration.max_pages,
            },
        }


__all__ = ["DocumentVendorProfileService"]
