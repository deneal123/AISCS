"""Atomic publication of trusted, renderer-owned document source bundles."""

from __future__ import annotations

import hashlib
import io
import json
import posixpath
import re
import secrets
import shlex
import tarfile
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from domain.files import safe_path

from application.documents.projects import DocumentProjectError

_CONTENT_PATH = re.compile(r"^content/[A-Za-z0-9_.-]{1,160}\.tex$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_FIXED_PATHS = frozenset({"main.tex", "bibliography/references.bib", ".gpthub-authoring.json"})
MAX_SOURCE_FILE_BYTES = 750_000
MAX_SOURCE_BUNDLE_BYTES = 2_000_000


class RunCommand(Protocol):
    async def __call__(
        self, item: Any, command: str, *, stdin_payload: bytes | None = None
    ) -> Any: ...


Snapshot = Callable[[Any, str], Awaitable[Any]]
Revision = Callable[[Any], Awaitable[str]]


def _safe_source_path(value: object) -> str | None:
    path = str(value or "").replace("\\", "/").strip()
    if path in _FIXED_PATHS or _CONTENT_PATH.fullmatch(path):
        return path
    return None


def _archive(
    files: Mapping[str, str], *, authoring_version: int, draft_digest: str
) -> tuple[bytes, tuple[str, ...]]:
    if not 1 <= int(authoring_version) <= 1_000_000 or not _DIGEST.fullmatch(draft_digest):
        raise DocumentProjectError("authoring_invalid")
    normalized: dict[str, bytes] = {}
    total = 0
    for raw_path, raw_content in files.items():
        path = _safe_source_path(raw_path)
        if path is None or not isinstance(raw_content, str):
            raise DocumentProjectError("authoring_invalid")
        content = raw_content.replace("\x00", "").encode("utf-8")
        if len(content) > MAX_SOURCE_FILE_BYTES:
            raise DocumentProjectError("source_too_large")
        total += len(content)
        if total > MAX_SOURCE_BUNDLE_BYTES:
            raise DocumentProjectError("source_too_large")
        normalized[path] = content
    if "main.tex" not in normalized:
        raise DocumentProjectError("authoring_invalid")
    manifest = normalized.get(".gpthub-authoring.json")
    if manifest is None:
        manifest = json.dumps(
            {
                "schema_version": 1,
                "draft_version": authoring_version,
                "draft_digest": draft_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        normalized[".gpthub-authoring.json"] = manifest
    try:
        raw_manifest = json.loads(manifest)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise DocumentProjectError("authoring_invalid") from exc
    if (
        not isinstance(raw_manifest, dict)
        or raw_manifest.get("draft_version") != authoring_version
        or raw_manifest.get("draft_digest") != draft_digest
    ):
        raise DocumentProjectError("authoring_invalid")
    draft = raw_manifest.get("draft")
    if draft is not None:
        computed = hashlib.sha256(
            json.dumps(
                draft,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if computed != draft_digest:
            raise DocumentProjectError("authoring_invalid")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, content in sorted(normalized.items()):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o644
            info.mtime = 1_704_067_200
            archive.addfile(info, io.BytesIO(content))
    return output.getvalue(), tuple(sorted(normalized))


class DocumentSourceService:
    """Publish all renderer-managed files under one workspace operation guard."""

    def __init__(
        self,
        run_command: RunCommand,
        snapshot: Snapshot,
        revision: Revision,
        projects: Any,
    ) -> None:
        self._run = run_command
        self._snapshot = snapshot
        self._revision = revision
        self._projects = projects

    async def _rollback(
        self,
        item: Any,
        *,
        project: str,
        stage: str,
        backup: str,
    ) -> None:
        command = (
            f"rm -rf {shlex.quote(stage)}; "
            f"if [ -d {shlex.quote(backup)} ]; then "
            f"rm -rf {shlex.quote(project)}; "
            f"mv {shlex.quote(backup)} {shlex.quote(project)}; fi"
        )
        try:
            await self._run(item, command)
        except Exception:
            pass

    async def publish(
        self,
        item: Any,
        *,
        path: str,
        files: Mapping[str, str],
        authoring_version: int,
        draft_digest: str,
    ) -> dict[str, object]:
        await self._projects.manifest(item, path)
        project = safe_path(item.policy.root, path)
        relative = posixpath.relpath(project, item.policy.root)
        payload, names = _archive(
            files,
            authoring_version=authoring_version,
            draft_digest=draft_digest,
        )
        token = secrets.token_hex(8)
        service_root = f"{item.policy.root}/.gpthub-document"
        stage = f"{service_root}/authoring-{token}"
        backup = f"{service_root}/authoring-backup-{token}"
        parent = posixpath.dirname(project)
        command = (
            f"set -eu; mkdir -p {shlex.quote(service_root)} {shlex.quote(parent)}; "
            f"rm -rf {shlex.quote(stage)} {shlex.quote(backup)}; "
            f"cp -a {shlex.quote(project)} {shlex.quote(stage)}; "
            f"rm -f {shlex.quote(stage + '/main.tex')} "
            f"{shlex.quote(stage + '/bibliography/references.bib')} "
            f"{shlex.quote(stage + '/.gpthub-authoring.json')}; "
            f"rm -rf {shlex.quote(stage + '/content')}; "
            f"mkdir -p {shlex.quote(stage + '/content')} {shlex.quote(stage + '/bibliography')}; "
            f"tar -C {shlex.quote(stage)} -xf -; "
            f"mv {shlex.quote(project)} {shlex.quote(backup)}; "
            f"if mv {shlex.quote(stage)} {shlex.quote(project)}; then "
            "echo __OK__; "
            f"else mv {shlex.quote(backup)} {shlex.quote(project)}; "
            f"rm -rf {shlex.quote(stage)}; echo __FAILED__; fi"
        )
        try:
            result = await self._run(item, command, stdin_payload=payload)
        except Exception as exc:
            await self._rollback(item, project=project, stage=stage, backup=backup)
            raise DocumentProjectError("authoring_publish_failed") from exc
        if "__OK__" not in str(result.stdout or ""):
            await self._rollback(item, project=project, stage=stage, backup=backup)
            raise DocumentProjectError("authoring_publish_failed")
        try:
            snapshot = await self._snapshot(item, "document_authoring")
        except Exception as exc:
            await self._rollback(item, project=project, stage=stage, backup=backup)
            raise DocumentProjectError("authoring_publish_failed") from exc
        if isinstance(snapshot, Mapping) and not snapshot.get("committed"):
            reason = str(snapshot.get("reason") or "")
            if reason != "no_changes":
                await self._rollback(item, project=project, stage=stage, backup=backup)
                raise DocumentProjectError("authoring_publish_failed")
        revision = str(snapshot.get("revision") or "") if isinstance(snapshot, Mapping) else ""
        if not revision:
            try:
                revision = await self._revision(item)
            except Exception as exc:
                raise DocumentProjectError("authoring_publish_failed") from exc
        if not revision:
            raise DocumentProjectError("authoring_publish_failed")
        try:
            await self._run(item, f"rm -rf {shlex.quote(backup)}")
        except Exception:
            pass
        return {
            "outcome": "published",
            "path": relative,
            "authoring_version": authoring_version,
            "draft_digest": draft_digest,
            "file_count": len(names),
            "revision": revision,
            "revision_changed": bool(snapshot.get("committed", True))
            if isinstance(snapshot, Mapping)
            else True,
        }


__all__ = ["DocumentSourceService", "MAX_SOURCE_BUNDLE_BYTES", "MAX_SOURCE_FILE_BYTES"]
