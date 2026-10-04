"""Private, atomic checkpoints for resumable semantic document authoring."""

from __future__ import annotations

import hashlib
import json
import posixpath
import secrets
import shlex
import time
from collections.abc import Mapping
from typing import Any

from domain.files import safe_path

from application.documents.checkpoint_storage import LOCAL_CHECKPOINT, checkpoint_digest_command
from application.documents.projects import DocumentProjectError

MAX_CHECKPOINT_BYTES = 2_000_000
_STAGES = frozenset({"outline", "section_authoring", "complete"})


def _checkpoint_payload(
    path: str,
    value: Mapping[str, Any],
    *,
    request_digest: str,
    evidence_digest: str,
) -> bytes:
    stage = str(value.get("stage") or "")
    outline = value.get("outline")
    blocks = value.get("blocks")
    if (
        value.get("schema_version") != 1
        or {
            "project_path",
            "request_digest",
            "evidence_digest",
            "updated_at",
            "source_digest",
        }.intersection(value)
        or stage not in _STAGES
        or not isinstance(outline, dict)
        or not isinstance(blocks, list)
        or len(blocks) > 120
        or not isinstance(value.get("accepted_section_ids"), list)
        or not isinstance(value.get("repair_used"), bool)
        or type(value.get("draft_version", 1)) is not int
        or not 1 <= value.get("draft_version", 1) <= 1_000_000
        or len(request_digest) != 64
        or len(evidence_digest) != 64
    ):
        raise DocumentProjectError("authoring_invalid")
    try:
        bytes.fromhex(request_digest)
        bytes.fromhex(evidence_digest)
    except ValueError as exc:
        raise DocumentProjectError("authoring_invalid") from exc
    payload = json.dumps(
        {
            **dict(value),
            "project_path": path,
            "request_digest": request_digest,
            "evidence_digest": evidence_digest,
            "updated_at": int(time.time()),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > MAX_CHECKPOINT_BYTES:
        raise DocumentProjectError("source_too_large")
    return payload


def _checkpoint_path(root: str, project_path: str) -> str:
    digest = hashlib.sha256(project_path.encode("utf-8")).hexdigest()
    return f"{root}/.gpthub-document/checkpoints/{digest}.json"


def _lookup_script(root: str) -> str:
    """Return a syntax-valid bounded scanner for private checkpoint manifests."""

    return (
        "import glob,json,sys\n"
        "request_digest,evidence_digest=sys.argv[1:3]\n"
        "found=[]\n"
        f"files=glob.glob({root!r}+'/*.json')[:256]\n"
        "for name in files:\n"
        " try:\n"
        "  with open(name,encoding='utf-8') as source:\n"
        "   value=json.load(source)\n"
        "  if (isinstance(value,dict) and "
        "value.get('request_digest')==request_digest and "
        "value.get('evidence_digest')==evidence_digest):\n"
        "   found.append(value)\n"
        " except (OSError,ValueError,TypeError):\n"
        "  pass\n"
        "found.sort(key=lambda value:int(value.get('updated_at') or 0),reverse=True)\n"
        "print(json.dumps(found[0] if found else None,separators=(',',':')))\n"
    )


class DocumentCheckpointService:
    """Persist accepted authoring progress outside the visible worktree and Git."""

    def __init__(self, run_command: Any, projects: Any) -> None:
        self._run = run_command
        self._projects = projects

    async def _read_local(self, item: Any, project: str) -> dict[str, Any] | None:
        destination = shlex.quote(f"{project}/{LOCAL_CHECKPOINT}")
        result = await self._run(
            item,
            f"if [ -f {destination} ]; then head -c {MAX_CHECKPOINT_BYTES + 1} "
            f"{destination}; else echo null; fi",
        )
        raw = str(result.stdout or "null")
        if len(raw.encode("utf-8")) > MAX_CHECKPOINT_BYTES:
            raise DocumentProjectError("authoring_checkpoint_failed")
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise DocumentProjectError("authoring_checkpoint_failed") from exc
        if value is not None and not isinstance(value, dict):
            raise DocumentProjectError("authoring_checkpoint_failed")
        return value

    async def _digest(self, item: Any, project: str) -> str:
        result = await self._run(item, checkpoint_digest_command(project))
        digest = str(result.stdout or "").strip()
        if len(digest) != 64:
            raise DocumentProjectError("authoring_checkpoint_failed")
        try:
            bytes.fromhex(digest)
        except ValueError as exc:
            raise DocumentProjectError("authoring_checkpoint_failed") from exc
        return digest

    async def _checked_local(self, item: Any, project: str) -> dict[str, Any] | None:
        value = await self._read_local(item, project)
        if value is not None:
            if value.get("project_path") != posixpath.relpath(project, item.policy.root):
                raise DocumentProjectError("source_changed")
            if value.get("source_digest") != await self._digest(item, project):
                raise DocumentProjectError("source_changed")
        return value

    async def prepare_publication(
        self, item: Any, project: str, files: Mapping[str, str]
    ) -> bytes | None:
        """Rebase only renderer-confirmed complete state, before touching the worktree."""
        value = await self._checked_local(item, project)
        if value is None:
            return None
        try:
            manifest = json.loads(files.get(".gpthub-authoring.json") or "null")
            draft = manifest.get("draft") if isinstance(manifest, dict) else None
        except (TypeError, ValueError) as exc:
            raise DocumentProjectError("authoring_invalid") from exc
        if (
            value.get("stage") != "complete"
            or not isinstance(draft, dict)
            or not isinstance(draft.get("blocks"), list)
        ):
            raise DocumentProjectError("authoring_invalid")
        value["blocks"] = draft["blocks"]
        value["draft_version"] = manifest["draft_version"]
        value["outline"] = {**value["outline"], "title": draft["title"]}
        value["updated_at"] = int(time.time())
        payload = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(payload) > MAX_CHECKPOINT_BYTES:
            raise DocumentProjectError("source_too_large")
        return payload

    async def write(
        self,
        item: Any,
        *,
        path: str,
        checkpoint: Mapping[str, Any],
        revision: str,
        request_digest: str,
        evidence_digest: str,
    ) -> dict[str, object]:
        await self._projects.manifest(item, path)
        project = safe_path(item.policy.root, path)
        relative = posixpath.relpath(project, item.policy.root)
        payload = _checkpoint_payload(
            relative,
            checkpoint,
            request_digest=request_digest,
            evidence_digest=evidence_digest,
        )
        await self._checked_local(item, project)
        value = json.loads(payload)
        value["source_digest"] = await self._digest(item, project)
        payload = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(payload) > MAX_CHECKPOINT_BYTES:
            raise DocumentProjectError("source_too_large")
        destination = _checkpoint_path(item.policy.root, relative)
        temporary = f"{destination}.{secrets.token_hex(6)}.tmp"
        local = f"{project}/{LOCAL_CHECKPOINT}"
        local_temporary = f"{local}.{secrets.token_hex(6)}.tmp"
        command = (
            f"set -eu; mkdir -p {shlex.quote(posixpath.dirname(destination))} "
            f"{shlex.quote(posixpath.dirname(local))}; "
            f"cat > {shlex.quote(temporary)}; chmod 600 {shlex.quote(temporary)}; "
            f"cp {shlex.quote(temporary)} {shlex.quote(local_temporary)}; "
            f"mv {shlex.quote(local_temporary)} {shlex.quote(local)}; "
            f"mv {shlex.quote(temporary)} {shlex.quote(destination)}"
        )
        try:
            await self._run(item, command, stdin_payload=payload)
        except Exception as exc:
            try:
                await self._run(
                    item, f"rm -f {shlex.quote(temporary)} {shlex.quote(local_temporary)}"
                )
            except Exception:
                pass
            raise DocumentProjectError("authoring_checkpoint_failed") from exc
        return {
            "outcome": "checkpointed",
            "stage": str(checkpoint.get("stage") or ""),
            "accepted_block_count": len(checkpoint.get("blocks") or []),
            "revision": revision,
            "revision_changed": False,
        }

    async def latest(
        self,
        item: Any,
        *,
        request_digest: str,
        evidence_digest: str,
    ) -> dict[str, object] | None:
        for value in (request_digest, evidence_digest):
            if len(value) != 64:
                raise DocumentProjectError("authoring_invalid")
            try:
                bytes.fromhex(value)
            except ValueError as exc:
                raise DocumentProjectError("authoring_invalid") from exc
        root = f"{item.policy.root}/.gpthub-document/checkpoints"
        script = _lookup_script(root)
        result = await self._run(
            item,
            "python -c "
            + shlex.quote(script)
            + " "
            + shlex.quote(request_digest)
            + " "
            + shlex.quote(evidence_digest),
        )
        try:
            value = json.loads(str(result.stdout or "null"))
        except (TypeError, ValueError) as exc:
            raise DocumentProjectError("authoring_checkpoint_failed") from exc
        if value is None:
            return None
        if not isinstance(value, dict):
            raise DocumentProjectError("authoring_checkpoint_failed")
        project_path = str(value.get("project_path") or "")
        await self._projects.manifest(item, project_path)
        project = safe_path(item.policy.root, project_path)
        local = await self._checked_local(item, project)
        if local is None or any(
            local.get(key) != value.get(key)
            for key in ("project_path", "request_digest", "evidence_digest")
        ):
            # Legacy/unanchored state is preserved, but cannot authorize stale writes.
            raise DocumentProjectError("source_changed")
        value = local
        return {
            "path": project_path,
            "checkpoint": {
                key: value[key]
                for key in (
                    "schema_version",
                    "stage",
                    "outline",
                    "blocks",
                    "accepted_section_ids",
                    "repair_used",
                    "draft_version",
                )
                if key in value
            },
        }


__all__ = ["DocumentCheckpointService", "MAX_CHECKPOINT_BYTES", "_lookup_script"]
