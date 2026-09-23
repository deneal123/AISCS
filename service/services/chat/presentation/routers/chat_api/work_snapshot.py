"""Safe projections for the versioned Work Hub read model."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException

from service.services.files.application.file_saver_service import (
    FileSaverService,
    InvalidLibraryCursor,
)

WORK_SNAPSHOT_VERSION = 2


def workspace_state(state: str, *, recovered: bool = False) -> dict[str, Any]:
    return {
        "state": state,
        "entries": [],
        "history": [],
        "revision": "",
        "recovered": recovered,
    }


def room_state(state: str) -> dict[str, Any]:
    return {
        "state": state,
        "issues": [],
        "leases": [],
        "activity": [],
        "control": {"state": "running"},
    }


def unavailable_library() -> dict[str, Any]:
    return {
        "state": "unavailable",
        "items": [],
        "limit": 0,
        "next_cursor": None,
        "next_offset": None,
    }


def empty_work_snapshot(library: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": WORK_SNAPSHOT_VERSION,
        "workspace": workspace_state("absent"),
        "room": room_state("absent"),
        "library": library,
    }


def project_workspace_view(ref: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    root = str(ref.get("root") or view.get("root") or "/workspace")
    entries = [
        {**item, "path": str(item.get("path") or "").removeprefix(root).lstrip("/")}
        for item in (view.get("entries") or [])
        if isinstance(item, dict)
    ]
    return {
        "state": "ready",
        "entries": entries,
        "history": list(view.get("history") or []),
        "revision": str(view.get("revision") or ""),
        "recovered": bool(view.get("recovered")),
        "truncated": bool(view.get("truncated")),
    }


async def library_snapshot(
    file_service: FileSaverService,
    user_id: UUID,
    *,
    limit: int,
    offset: int = 0,
    cursor: str = "",
) -> dict[str, Any]:
    """Return one safe page while retaining alternate adapter compatibility."""
    page = getattr(file_service, "list_chat_library_page", None)
    if callable(page):
        try:
            result = await page(user_id, limit=limit, offset=offset, cursor=cursor)
        except TypeError:
            result = await page(user_id, limit=limit, offset=offset)
        except InvalidLibraryCursor as exc:
            raise HTTPException(status_code=400, detail="invalid_library_cursor") from exc
        if isinstance(result, dict):
            return {
                "state": "ready",
                "items": list(result.get("items") or []),
                "limit": limit,
                "next_cursor": result.get("next_cursor"),
                "next_offset": result.get("next_offset"),
            }
    items = await file_service.list_chat_library(user_id, limit=limit)
    return {
        "state": "ready",
        "items": items,
        "limit": limit,
        "next_cursor": None,
        "next_offset": None,
    }
