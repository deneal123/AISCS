"""Transactional two-phase workspace import orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from application.files import FileConflict
from application.importer import (
    IMPORTED_MARKER,
    KEPT_MARKER,
    MAX_TOTAL_BYTES,
    PUBLISH_FAILED_MARKER,
    ImportRefused,
    cleanup_staging_command,
    fetch,
    plan,
    publish_command,
    stage_command,
    unpack_command,
)

RunCommand = Callable[..., Awaitable[Any]]
Fetch = Callable[[str], Awaitable[bytes]]
Snapshot = Callable[[Any, str], Awaitable[dict[str, Any]]]
Revision = Callable[[Any], Awaitable[str]]


class ImportService:
    def __init__(
        self,
        run_command: RunCommand,
        snapshot: Snapshot,
        revision: Revision,
        fetcher: Fetch = fetch,
    ) -> None:
        self._run_command, self._snapshot, self._revision, self._fetch = (
            run_command,
            snapshot,
            revision,
            fetcher,
        )

    async def execute(
        self,
        item: Any,
        entries: list[dict] | None,
        *,
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        if expected_revision and await self._revision(item) != expected_revision:
            raise FileConflict("workspace revision changed")
        selected = plan(entries)
        if not selected:
            return {"files": [], "imported": 0, "kept": 0}
        staging_id = uuid.uuid4().hex
        try:
            results, staged, by_name = await self._stage_batch(item, selected, staging_id)
            if any(outcome["outcome"] == "stage_failed" for outcome in results):
                # A prepared subset is not a successful batch. Leave all
                # destinations untouched and discard every staged payload.
                for outcome in by_name.values():
                    outcome.update({"outcome": "stage_failed", "reason": "stage write failed"})
            elif staged:
                # Download/staging can take long enough for a second actor to
                # finish a mutation.  Do not publish a prepared batch over a
                # newer workspace state.
                if expected_revision and await self._revision(item) != expected_revision:
                    raise FileConflict("workspace revision changed")
                output = (
                    await self._run_command(
                        item, publish_command(item.policy.root, staging_id, staged)
                    )
                ).stdout or ""
                if PUBLISH_FAILED_MARKER in output:
                    for outcome in by_name.values():
                        outcome.update({"outcome": "publish_failed", "reason": "publish failed"})
                else:
                    for line in output.splitlines():
                        marker, _, name = line.partition("\t")
                        outcome = by_name.get(name)
                        if outcome is None:
                            continue
                        if marker == IMPORTED_MARKER:
                            outcome.update({"outcome": "imported", "imported": True})
                            item.imported.add(name)
                        elif marker == KEPT_MARKER:
                            outcome.update({"outcome": "kept", "kept": True})
                            item.imported.add(name)
                    for outcome in by_name.values():
                        if outcome["outcome"] == "staged":
                            outcome.update(
                                {"outcome": "publish_failed", "reason": "publish failed"}
                            )
                    for outcome in results:
                        if outcome.get("outcome") == "imported" and outcome[
                            "name"
                        ].lower().endswith(".zip"):
                            unpacked = await self._run_command(
                                item, unpack_command(item.policy.root, outcome["name"])
                            )
                            if "__OK__" in (unpacked.stdout or ""):
                                outcome["unpacked"] = True
        finally:
            # Even a failed first write can have created its staging directory.
            # Cancellation must not bypass cleanup or publish a prepared subset.
            await self._run_command(item, cleanup_staging_command(item.policy.root, staging_id))
        imported = sum(outcome.get("outcome") == "imported" for outcome in results)
        kept = sum(outcome.get("outcome") == "kept" for outcome in results)
        if imported:
            # IMPORT_MESSAGE was the old transport-level name; the durable
            # history contract accepts only the safe snapshot type below.
            await self._snapshot(item, "import")
        return {"files": results, "imported": imported, "kept": kept}

    async def _stage_batch(
        self, item: Any, entries: list[dict], staging_id: str
    ) -> tuple[list[dict], list[str], dict[str, dict]]:
        results, staged, by_name = [], [], {}
        total = 0
        for entry in entries:
            outcome = {"name": entry["name"], "imported": False}
            try:
                if total >= MAX_TOTAL_BYTES:
                    raise ImportRefused("import byte limit reached")
                data = await self._fetch(entry["url"])
                if len(data) > MAX_TOTAL_BYTES - total:
                    raise ImportRefused("import byte limit reached")
                total += len(data)
                command, content = stage_command(item.policy.root, staging_id, entry["name"], data)
                if "__OK__" not in (
                    (await self._run_command(item, command, stdin_payload=content)).stdout or ""
                ):
                    raise ImportRefused("stage write failed")
            except ImportRefused as exc:
                outcome.update({"outcome": "stage_failed", "reason": str(exc)[:200]})
                results.append(outcome)
                continue
            except Exception:
                outcome.update({"outcome": "stage_failed", "reason": "stage write failed"})
                results.append(outcome)
                continue
            outcome["outcome"] = "staged"
            results.append(outcome)
            by_name[entry["name"]] = outcome
            staged.append(entry["name"])
        return results, staged, by_name
