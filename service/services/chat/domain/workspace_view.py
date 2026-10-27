"""Credential-free workspace facts shared by read and preparation owners."""

from typing import Any


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
