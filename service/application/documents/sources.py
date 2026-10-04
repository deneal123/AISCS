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

from application.documents.checkpoint_storage import LOCAL_CHECKPOINT, checkpoint_rebase_command
from application.documents.projects import DocumentProjectError
from application.documents.source_exchange import exchange_marker, project_exchange_command
from application.documents.source_recovery import (
    JOURNAL_SEED,
    MAX_PENDING_PUBLICATIONS,
    journal_command,
    journal_path,
)

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
    files: Mapping[str, str],
    *,
    authoring_version: int,
    draft_digest: str,
    checkpoint_payload: bytes | None = None,
    publication_seed: bytes | None = None,
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
        if (
            not isinstance(draft, dict)
            or type(draft.get("version")) is not int
            or draft.get("version") != authoring_version
            or not isinstance(draft.get("title"), str)
            or not draft["title"].strip()
        ):
            raise DocumentProjectError("authoring_invalid")
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
    names = tuple(sorted(normalized))
    if checkpoint_payload is not None:
        normalized[LOCAL_CHECKPOINT] = checkpoint_payload
    if publication_seed is not None:
        normalized[JOURNAL_SEED] = publication_seed
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, content in sorted(normalized.items()):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o644
            info.mtime = 1_704_067_200
            archive.addfile(info, io.BytesIO(content))
    return output.getvalue(), names


class DocumentSourceService:
    """Publish all renderer-managed files under one workspace operation guard."""

    def __init__(
        self,
        run_command: RunCommand,
        snapshot: Snapshot,
        revision: Revision,
        projects: Any,
        checkpoints: Any = None,
        recovery: Any = None,
    ) -> None:
        self._run = run_command
        self._snapshot = snapshot
        self._revision = revision
        self._projects = projects
        self._checkpoints = checkpoints
        self._recovery = recovery

    async def recover(self, item: Any) -> None:
        if self._recovery is not None:
            counts = await self._recovery.recover(item)
            if counts["pending"] >= MAX_PENDING_PUBLICATIONS:
                raise DocumentProjectError("authoring_publish_failed")

    async def _rollback(
        self,
        item: Any,
        *,
        project: str,
        stage: str,
        backup: str,
        token: str,
    ) -> None:
        command = (
            f"set -eu; if [ -d {shlex.quote(backup)} ]; then "
            + project_exchange_command(project, backup)
            + f"rm -rf {shlex.quote(backup)}; "
            f"elif [ -f {shlex.quote(exchange_marker(stage, token))} ]; then "
            + project_exchange_command(project, stage)
            + "fi; "
            f"rm -rf {shlex.quote(stage)}; "
            f"rm -f {shlex.quote(exchange_marker(project, token))} "
            f"{shlex.quote(journal_path(item.policy.root, token))}"
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
        _archive(files, authoring_version=authoring_version, draft_digest=draft_digest)
        await self.recover(item)
        checkpoint_payload = (
            await self._checkpoints.prepare_publication(item, project, files)
            if self._checkpoints is not None
            else None
        )
        token = secrets.token_hex(8)
        publication_seed = (
            json.dumps(
                {
                    "schema_version": 1,
                    "token": token,
                    "project_path": relative,
                },
                separators=(",", ":"),
            ).encode()
            if self._recovery is not None
            else None
        )
        payload, names = _archive(
            files,
            authoring_version=authoring_version,
            draft_digest=draft_digest,
            checkpoint_payload=checkpoint_payload,
            publication_seed=publication_seed,
        )
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
            + (checkpoint_rebase_command(stage) if checkpoint_payload is not None else "")
            + (
                journal_command(item.policy.root, project, stage, token)
                if self._recovery is not None
                else ""
            )
            + f"mkdir -p {shlex.quote(project + '/.gpthub-document')}; "
            f"touch {shlex.quote(exchange_marker(project, token))}; "
            + project_exchange_command(project, stage)
            + f"mv {shlex.quote(stage)} {shlex.quote(backup)}; echo __OK__"
        )
        try:
            result = await self._run(item, command, stdin_payload=payload)
        except Exception as exc:
            await self._rollback(item, project=project, stage=stage, backup=backup, token=token)
            raise DocumentProjectError("authoring_publish_failed") from exc
        if "__OK__" not in str(result.stdout or ""):
            await self._rollback(item, project=project, stage=stage, backup=backup, token=token)
            raise DocumentProjectError("authoring_publish_failed")
        try:
            snapshot = await self._snapshot(item, "document_authoring")
        except Exception as exc:
            await self._rollback(item, project=project, stage=stage, backup=backup, token=token)
            raise DocumentProjectError("authoring_publish_failed") from exc
        if isinstance(snapshot, Mapping) and not snapshot.get("committed"):
            reason = str(snapshot.get("reason") or "")
            if reason != "no_changes":
                await self._rollback(item, project=project, stage=stage, backup=backup, token=token)
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
            await self._run(
                item,
                f"rm -rf {shlex.quote(backup)} && "
                f"rm -f {shlex.quote(journal_path(item.policy.root, token))}",
            )
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
