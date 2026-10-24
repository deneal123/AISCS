"""Долговечное намерение до compiler create; повтор никогда не выделяет новый процесс."""

import json
import shlex

from domain.documents.document_review import operation_build_id
from domain.files import safe_path

from .projects import DocumentProjectError
from .proposal_storage import STORE_SCRIPT


def existing_operation(manager, item, *, operation_id, project_path, expected_revision, final):
    build_id = operation_build_id(str(item.workspace_id), operation_id)
    existing = manager._builds.get(build_id)
    if existing is not None and (
        existing.workspace_id != item.workspace_id
        or existing.operation_id != operation_id
        or existing.project_path != safe_path(item.policy.root, project_path)
        or existing.source_revision != expected_revision
        or existing.final is not final
    ):
        raise DocumentProjectError("source_changed")
    return existing


async def claim_operation(registry, item, *, operation_id, project_path, expected_revision, final):
    build_id = operation_build_id(str(item.workspace_id), operation_id)
    payload = json.dumps(
        {
            "version": 1,
            "operation_id": operation_id,
            "workspace_id": item.workspace_id,
            "project_path": safe_path(item.policy.root, project_path),
            "expected_revision": expected_revision,
            "final": final,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    directory = safe_path(item.policy.root, ".gpthub-document/build-operations")
    async with registry.operation(item):
        result = await registry.exec_raw(
            item,
            f"python -c {shlex.quote(STORE_SCRIPT)} {shlex.quote(directory)} {build_id}",
            stdin_payload=payload,
            max_output_chars=128,
        )
    if (
        getattr(result, "exit_code", None) != 0
        or getattr(result, "timed_out", False)
        or getattr(result, "truncated", False)
        or str(result.stdout or "").strip() not in {"stored", "reused"}
    ):
        raise DocumentProjectError("runtime_unavailable")
    return str(result.stdout).strip() == "stored"
