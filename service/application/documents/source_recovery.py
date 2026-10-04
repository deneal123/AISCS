"""Bounded private journals for interrupted managed-source publication."""

from __future__ import annotations

import asyncio
import json
import posixpath
import re
import shlex
from typing import Any

from domain.files import safe_path

from application.documents.checkpoint_storage import checkpoint_digest_command
from application.documents.projects import DocumentProjectError
from application.documents.source_exchange import exchange_marker

JOURNAL_SEED = ".gpthub-document/source-publication.json"
_TOKEN = re.compile(r"^[a-f0-9]{16}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
MAX_PENDING_PUBLICATIONS = 64


def journal_path(root: str, token: str) -> str:
    if not _TOKEN.fullmatch(token):
        raise DocumentProjectError("authoring_publish_failed")
    return f"{root}/.gpthub-document/source-publications/{token}.json"


def journal_command(root: str, project: str, stage: str, token: str) -> str:
    destination = journal_path(root, token)
    script = (
        "import json,os,sys; source,target,old,new=sys.argv[1:5]; "
        "value=json.load(open(source,encoding='utf-8')); "
        "value.update(old_digest=old,new_digest=new); "
        "temporary=target+'.tmp'; output=open(temporary,'w',encoding='utf-8'); "
        "json.dump(value,output,sort_keys=True,separators=(',',':')); output.close(); "
        "os.chmod(temporary,0o600); os.replace(temporary,target)"
    )
    return (
        f"mkdir -p {shlex.quote(posixpath.dirname(destination))}; "
        f"source_old=$({checkpoint_digest_command(project)}); "
        f"source_new=$({checkpoint_digest_command(stage)}); "
        f"python -c {shlex.quote(script)} {shlex.quote(stage + '/' + JOURNAL_SEED)} "
        f'{shlex.quote(destination)} "$source_old" "$source_new"; '
    )


def _scan_command(root: str) -> str:
    directory = f"{root}/.gpthub-document/source-publications"
    script = (
        "import glob,json,os,sys\n"
        "records=[]\n"
        f"names=sorted(glob.glob({directory!r}+'/*.json'))\n"
        f"if len(names)>{MAX_PENDING_PUBLICATIONS}: raise RuntimeError('source_registry_full')\n"
        "for name in names:\n"
        " if os.path.islink(name) or os.path.getsize(name)>4096:\n"
        "  raise RuntimeError('source_journal_invalid')\n"
        " value=json.load(open(name,encoding='utf-8'))\n"
        " records.append({'filename':os.path.basename(name),'value':value})\n"
        "print(json.dumps(records,separators=(',',':')))\n"
    )
    return f"python -c {shlex.quote(script)}"


class SourcePublicationRecovery:
    def __init__(self, run_command: Any, snapshot: Any) -> None:
        self._run, self._snapshot = run_command, snapshot
        self._health = {"recovered": 0, "pending": 0, "conflicted": 0}

    def health(self) -> dict[str, int]:
        return dict(self._health)

    def _record(self, item: Any, record: Any) -> tuple[dict, str]:
        if not isinstance(record, dict) or not isinstance(record.get("value"), dict):
            raise DocumentProjectError("authoring_publish_failed")
        value = record["value"]
        token = str(value.get("token") or "")
        relative = str(value.get("project_path") or "")
        if (
            value.get("schema_version") != 1
            or not _TOKEN.fullmatch(token)
            or record.get("filename") != token + ".json"
            or any(
                not _DIGEST.fullmatch(str(value.get(key) or ""))
                for key in ("old_digest", "new_digest")
            )
        ):
            raise DocumentProjectError("authoring_publish_failed")
        try:
            project = safe_path(item.policy.root, relative)
        except Exception as exc:
            raise DocumentProjectError("authoring_publish_failed") from exc
        if posixpath.relpath(project, item.policy.root) != relative or relative in {"", "."}:
            raise DocumentProjectError("authoring_publish_failed")
        if relative.split("/", 1)[0] in {".gpthub-document", ".git"}:
            raise DocumentProjectError("authoring_publish_failed")
        return value, project

    async def recover(self, item: Any) -> dict[str, int]:
        result = await self._run(item, _scan_command(item.policy.root))
        try:
            records = json.loads(str(result.stdout or ""))
        except (ValueError, TypeError) as exc:
            raise DocumentProjectError("authoring_publish_failed") from exc
        if not isinstance(records, list) or len(records) > MAX_PENDING_PUBLICATIONS:
            raise DocumentProjectError("authoring_publish_failed")
        counts = {"recovered": 0, "pending": len(records), "conflicted": 0}
        for raw in records:
            value, project = self._record(item, raw)
            digest = str(
                (await self._run(item, checkpoint_digest_command(project))).stdout or ""
            ).strip()
            if digest not in {value["old_digest"], value["new_digest"]}:
                counts["conflicted"] += 1
                continue
            if digest == value["new_digest"] and digest != value["old_digest"]:
                snapshot = await self._snapshot(item, "document_authoring")
                if not isinstance(snapshot, dict) or (
                    not snapshot.get("committed") and snapshot.get("reason") != "no_changes"
                ):
                    raise DocumentProjectError("authoring_publish_failed")
            token = value["token"]
            private = f"{item.policy.root}/.gpthub-document"
            # Delete only exact generated private paths, never the public project.
            await self._run(
                item,
                f"set -eu; rm -rf {shlex.quote(private + '/authoring-' + token)} "
                f"{shlex.quote(private + '/authoring-backup-' + token)}; "
                f"rm -f {shlex.quote(exchange_marker(project, token))} "
                f"{shlex.quote(journal_path(item.policy.root, token))}",
            )
            counts["recovered"] += 1
            counts["pending"] -= 1
        self._health = counts
        return counts

    async def reconcile_registry(self, registry: Any) -> None:
        totals = {"recovered": 0, "pending": 0, "conflicted": 0}
        for item in await registry.active_workspaces():
            try:
                async with registry.operation(item):
                    counts = await self.recover(item)
                for key in totals:
                    totals[key] += counts[key]
            except Exception:
                totals["conflicted"] += 1
        self._health = totals

    async def reconcile_forever(self, registry: Any) -> None:
        while True:
            await asyncio.sleep(60)
            await self.reconcile_registry(registry)
