"""Safe projections for the versioned Work Hub read model."""

from __future__ import annotations

from inspect import signature
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from service.services.chat.domain.workspace_view import (
    project_workspace_view as project_workspace_view,
)
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


async def library_snapshot(
    file_service: FileSaverService,
    user_id: UUID,
    *,
    limit: int,
    offset: int = 0,
    cursor: str = "",
    search: str = "",
) -> dict[str, Any]:
    """Return one safe page while retaining alternate adapter compatibility."""
    page = getattr(file_service, "list_chat_library_page", None)
    if callable(page):
        options = {"limit": limit, "offset": offset, "cursor": cursor}
        if search:
            options["search"] = search
        # Inspect compatibility before invocation. A TypeError raised inside a
        # cursor-aware adapter is an operation failure, not permission to retry
        # a different page and report it as successful.
        contract = signature(page)
        try:
            contract.bind(user_id, **options)
        except TypeError:
            options.pop("cursor")
            contract.bind(user_id, **options)
        try:
            result = await page(user_id, **options)
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
    if search:
        raise HTTPException(status_code=503, detail="library_search_unavailable")
    items = await file_service.list_chat_library(user_id, limit=limit)
    return {
        "state": "ready",
        "items": items,
        "limit": limit,
        "next_cursor": None,
        "next_offset": None,
    }
