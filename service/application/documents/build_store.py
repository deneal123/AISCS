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
INVENTORY_COMPLETE = "__GPTHUB_MANIFESTS_COMPLETE__\n"


def _completed(result: Any) -> bool:
    code = getattr(result, "exit_code", None)
    return (
        type(code) is int
        and code == 0
        and not getattr(result, "truncated", False)
        and not getattr(result, "timed_out", False)
        and isinstance(getattr(result, "stdout", None), str)
    )


class BuildManifestStore:
    def _root(self, item: Any) -> str:
        return safe_path(item.policy.root, ".gpthub-document/jobs")

    def _path(self, item: Any, build_id: str) -> str:
        safe_id = "".join(ch for ch in str(build_id) if ch.isalnum() or ch in {"-", "_"})[:128]
        if not safe_id or safe_id != str(build_id):
            raise ValueError("invalid build id")
        return posixpath.join(self._root(item), f"{safe_id}.json")

    def _directory_checks(self, item: Any, *, missing_is_empty: bool) -> str:
        root = self._root(item)
        base = shlex.quote(item.policy.root)
        checks = (
            f"test -d {base} && test ! -L {base} && test -r {base} && test -x {base} || exit 1; "
        )
        for directory in (posixpath.dirname(root), root):
            path = shlex.quote(directory)
            missing = "exit 0" if missing_is_empty else f"mkdir -p {path} || exit 1"
            checks += (
                f"test ! -L {path} || exit 1; "
                f"if [ ! -e {path} ]; then {missing}; fi; "
                f"test -d {path} && test -r {path} && test -x {path} || exit 1; "
            )
        return checks

    async def save(self, registry: Any, item: Any, build: DocumentBuild) -> None:
        payload = json.dumps(
            build.manifest_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        command, stdin = write_command(item.policy.root, self._path(item, build.build_id), payload)
        target = shlex.quote(self._path(item, build.build_id))
        command = (
            self._directory_checks(item, missing_is_empty=False)
            + f"test ! -L {target} || exit 1; "
            + f"if [ -e {target} ]; then test -f {target} || exit 1; fi; "
            + command
        )
        result = await registry.exec_raw(item, command, stdin_payload=stdin, max_output_chars=1024)
        expected = f"__OK__ {len(payload.encode('utf-8'))}\n"
        if not _completed(result) or result.stdout != expected:
            raise RuntimeError("build manifest unavailable")

    async def load(self, registry: Any, item: Any) -> tuple[DocumentBuild, ...]:
        root = self._root(item)
        command = (
            self._directory_checks(item, missing_is_empty=True)
            + f"find {shlex.quote(root)} -maxdepth 1 -name '*.json' "
            "-exec sh -c "
            + shlex.quote(
                'for f do test -f "$f" && test ! -L "$f" || exit 1; '
                'tr -d "\\n" < "$f" || exit 1; printf "\\n"; done'
            )
            + " sh {} +"
        )
        command = f"( {command} ) && printf {shlex.quote(INVENTORY_COMPLETE)}"
        result = await registry.exec_raw(item, command, max_output_chars=2 * 1024 * 1024)
        if not _completed(result) or not result.stdout.endswith(INVENTORY_COMPLETE):
            raise RuntimeError("build manifest inventory unavailable")
        lines = result.stdout[: -len(INVENTORY_COMPLETE)].splitlines()
        if len(lines) > 256:
            raise RuntimeError("build manifest inventory unavailable")
        builds: list[DocumentBuild] = []
        seen_ids: set[str] = set()
        for line in lines:
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError("invalid manifest object")
                build = DocumentBuild.from_manifest(raw)
            except (AttributeError, TypeError, ValueError, OverflowError):
                raise RuntimeError("build manifest inventory invalid") from None
            if build.workspace_id != item.workspace_id or build.build_id in seen_ids:
                raise RuntimeError("build manifest inventory invalid")
            seen_ids.add(build.build_id)
            builds.append(build)
        return tuple(sorted(builds, key=lambda build: build.build_id))

    async def delete(self, registry: Any, item: Any, build_id: str) -> None:
        path = self._path(item, build_id)
        result = await registry.exec_raw(
            item,
            f"rm -f {shlex.quote(path)} && echo __OK__",
            max_output_chars=128,
        )
        if not _completed(result) or result.stdout != "__OK__\n":
            raise RuntimeError("build manifest deletion unavailable")

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
        result = await registry.exec_raw(item, checks + " && echo __OK__", max_output_chars=128)
        code = getattr(result, "exit_code", None)
        if (
            type(code) is not int
            or code not in {0, 1}
            or getattr(result, "timed_out", False)
            or getattr(result, "truncated", False)
            or (code == 0 and getattr(result, "stdout", None) != "__OK__\n")
        ):
            raise RuntimeError("artifact verification unavailable")
        return code == 0

    @staticmethod
    def prune_candidates(
        builds: tuple[DocumentBuild, ...], now: float | None = None, *, reserved: int = 0
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
            and not item.operation_id
            and not item.compiler_ref
            and current - (item.completed_at or item.created_at) > PREVIEW_RETENTION_SEC
        ]
        remaining = [item for item in completed if item.build_id not in set(expired_preview)]
        overflow = max(0, len(remaining) + reserved - MAX_COMPLETED_PER_WORKSPACE)
        removable = [
            item
            for item in remaining
            if not item.final and not item.compiler_ref and not item.operation_id
        ]
        overflow_ids = (item.build_id for item in removable[:overflow])
        return tuple(dict.fromkeys([*expired_preview, *overflow_ids]))


__all__ = ["ACTIVE_STATES", "BuildManifestStore"]
