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
        or stage not in _STAGES
        or not isinstance(outline, dict)
        or not isinstance(blocks, list)
        or len(blocks) > 120
        or not isinstance(value.get("accepted_section_ids"), list)
        or not isinstance(value.get("repair_used"), bool)
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
            "project_path": path,
            "request_digest": request_digest,
            "evidence_digest": evidence_digest,
            "updated_at": int(time.time()),
            **dict(value),
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
        destination = _checkpoint_path(item.policy.root, relative)
        temporary = f"{destination}.{secrets.token_hex(6)}.tmp"
        command = (
            f"set -eu; mkdir -p {shlex.quote(posixpath.dirname(destination))}; "
            f"cat > {shlex.quote(temporary)}; chmod 600 {shlex.quote(temporary)}; "
            f"mv {shlex.quote(temporary)} {shlex.quote(destination)}"
        )
        try:
            await self._run(item, command, stdin_payload=payload)
        except Exception as exc:
            try:
                await self._run(item, f"rm -f {shlex.quote(temporary)}")
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
                )
                if key in value
            },
        }


__all__ = ["DocumentCheckpointService", "MAX_CHECKPOINT_BYTES", "_lookup_script"]
