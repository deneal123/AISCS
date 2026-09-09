"""Durable, workspace-local build manifests used for restart recovery."""

from __future__ import annotations

import json
import posixpath
import shlex
import time
from typing import Any

from domain.documents import DocumentBuild
from domain.files import safe_path, write_command

ACTIVE_STATES = frozenset(
    {"queued", "preparing", "building", "deterministic_audit", "visual_audit", "publishing"}
)
MAX_COMPLETED_PER_WORKSPACE = 64
PREVIEW_RETENTION_SEC = 24 * 60 * 60


class BuildManifestStore:
    def _root(self, item: Any) -> str:
        return safe_path(item.policy.root, ".gpthub-document/jobs")

    def _path(self, item: Any, build_id: str) -> str:
        safe_id = "".join(ch for ch in str(build_id) if ch.isalnum() or ch in {"-", "_"})[:128]
        if not safe_id or safe_id != str(build_id):
            raise ValueError("invalid build id")
        return posixpath.join(self._root(item), f"{safe_id}.json")

    async def save(self, registry: Any, item: Any, build: DocumentBuild) -> None:
        payload = json.dumps(
            build.manifest_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        command, stdin = write_command(item.policy.root, self._path(item, build.build_id), payload)
        result = await registry.exec_raw(item, command, stdin_payload=stdin, max_output_chars=1024)
        if "__OK__" not in str(result.stdout or ""):
            raise RuntimeError("build manifest unavailable")

    async def load(self, registry: Any, item: Any) -> tuple[DocumentBuild, ...]:
        root = self._root(item)
        command = (
            f"if [ ! -d {shlex.quote(root)} ]; then exit 0; fi; "
            f"find {shlex.quote(root)} -maxdepth 1 -type f -name '*.json' -print | "
            "sort | while IFS= read -r f; do "
            "tr -d '\\n' < \"$f\"; printf '\\n'; done"
        )
        result = await registry.exec_raw(item, command, max_output_chars=2 * 1024 * 1024)
        builds: list[DocumentBuild] = []
        for line in str(result.stdout or "").splitlines()[:256]:
            try:
                raw = json.loads(line)
                build = DocumentBuild.from_manifest(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if build.workspace_id == item.workspace_id:
                builds.append(build)
        return tuple(builds)

    async def delete(self, registry: Any, item: Any, build_id: str) -> None:
        path = self._path(item, build_id)
        await registry.exec_raw(
            item,
            f"rm -f {shlex.quote(path)}",
            max_output_chars=128,
        )

    async def verify_artifacts(self, registry: Any, item: Any, build: DocumentBuild) -> bool:
        if not build.artifacts:
            return False
        checks = " && ".join(
            f"test -f {shlex.quote(artifact.internal_path)} && "
            f"test \"$(sha256sum {shlex.quote(artifact.internal_path)} | cut -d' ' -f1)\" = "
            f"{shlex.quote(artifact.sha256)}"
            for artifact in build.artifacts
        )
        if build.state in {"visual_pending", "visual_audit"}:
            if not build.visual_bundle_path or len(build.visual_bundle_sha256) != 64:
                return False
            checks += (
                f" && test -f {shlex.quote(build.visual_bundle_path)} && "
                f"test \"$(sha256sum {shlex.quote(build.visual_bundle_path)} | cut -d' ' -f1)\" = "
                f"{shlex.quote(build.visual_bundle_sha256)}"
            )
        result = await registry.exec_raw(item, checks, max_output_chars=128)
        return int(getattr(result, "exit_code", 0) or 0) == 0

    @staticmethod
    def prune_candidates(
        builds: tuple[DocumentBuild, ...], now: float | None = None
    ) -> tuple[str, ...]:
        current = time.time() if now is None else now
        completed = sorted(
            (item for item in builds if item.state not in ACTIVE_STATES),
            key=lambda item: (item.completed_at or item.created_at, item.build_id),
        )
        expired_preview = [
            item.build_id
            for item in completed
            if not item.final
            and current - (item.completed_at or item.created_at) > PREVIEW_RETENTION_SEC
        ]
        remaining = [item for item in completed if item.build_id not in set(expired_preview)]
        overflow = max(0, len(remaining) - MAX_COMPLETED_PER_WORKSPACE)
        overflow_ids = (item.build_id for item in remaining[:overflow])
        return tuple(dict.fromkeys([*expired_preview, *overflow_ids]))


__all__ = ["ACTIVE_STATES", "BuildManifestStore"]
