"""Verify current source bytes, not a model's finish report or a stale write ACK."""

import asyncio

from service.domain.tools.ide.tools import _read_result
from service.domain.tools.workspace.client import WorkspaceUnavailable, call
from service.shared import deadline


async def verify_written_files(execution) -> bool:
    """Read back confirmed files at the task boundary; keep all source text private.

    Directories have no content digest and are not proof that requested source was
    created. This check does not claim that code ran or user acceptance passed.
    """
    workspace = execution.workspace
    if workspace.ide_unconfirmed:
        return False
    reference = execution.resources.workspace_ref or {}
    try:
        for path, digest in workspace.ide_writes.items():
            if execution.cancelled:
                return False
            if digest is None:
                continue
            result = await call(reference, "ide/file", {"path": path})
            _, evidence = _read_result(result)
            if result.get("path") != path or evidence is None or evidence["digest"] != digest:
                return False
    except (WorkspaceUnavailable, ValueError, TypeError, KeyError, AttributeError):
        return False
    return True


async def finalize_ide_evidence(execution) -> None:
    reference = execution.resources.workspace_ref or {}
    if not execution.task.active or not isinstance(reference.get("ide_context"), dict):
        return
    if not execution.workspace.ide_writes or execution.cancelled:
        return
    try:
        async with asyncio.timeout(deadline.clamp(10.0)):
            verified = await verify_written_files(execution)
    except TimeoutError:
        verified = False
    if not verified and not execution.cancelled:
        execution.task.stop_reason = "verification_failed"
        execution.workspace.ide_summary = (
            "Не удалось подтвердить актуальное содержимое изменённых файлов. "
            "Проверьте проект; автоматическая повторная запись не выполнялась."
        )
