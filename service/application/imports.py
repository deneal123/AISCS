"""Transactional two-phase workspace import orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

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


class ImportService:
    def __init__(self, run_command: RunCommand, snapshot: Snapshot, fetcher: Fetch = fetch) -> None:
        self._run_command, self._snapshot, self._fetch = run_command, snapshot, fetcher

    async def execute(self, item: Any, entries: list[dict] | None) -> dict[str, Any]:
        results, staged, by_name = [], [], {}
        total, staging_id = 0, uuid.uuid4().hex
        for entry in plan(entries):
            outcome = {"name": entry["name"], "imported": False}
            try:
                if total >= MAX_TOTAL_BYTES:
                    raise ImportRefused("import byte limit reached")
                data = await self._fetch(entry["url"])
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
        if staged:
            try:
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
                await self._run_command(item, cleanup_staging_command(item.policy.root, staging_id))
        imported = sum(outcome.get("outcome") == "imported" for outcome in results)
        kept = sum(outcome.get("outcome") == "kept" for outcome in results)
        if imported:
            # IMPORT_MESSAGE was the old transport-level name; the durable
            # history contract accepts only the safe snapshot type below.
            await self._snapshot(item, "import")
        return {"files": results, "imported": imported, "kept": kept}
