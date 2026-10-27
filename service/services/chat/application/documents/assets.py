"""Project-scoped Library intake through the existing fenced import transport."""

from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from fastapi import HTTPException

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".pdf"})


async def document_asset_source(
    client: Any, ref: dict, *, path: str, revision: str, source: dict, file_id: UUID
) -> tuple[dict, str]:
    """Never accept a browser destination, URL, filename or claimed ownership."""
    project = await client.document_project_status(ref, path=path)
    if not isinstance(project, dict) or project.get("path") != path:
        raise HTTPException(status_code=404, detail="document_project_not_found")
    if project.get("revision") != revision:
        raise HTTPException(status_code=409, detail="source_changed")
    suffix = PurePosixPath(str(source.get("name") or "")).suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        raise HTTPException(status_code=422, detail="document_asset_unsupported")
    asset_path = f"figures/library_{file_id.hex}{suffix}"
    return {**source, "name": f"{path}/{asset_path}"}, asset_path


def confirmed_asset_import(result: dict, destination: str) -> bool:
    """Aggregate counts alone must not advertise a project asset as available."""
    files = result.get("files")
    if not isinstance(files, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("name") == destination
        and item.get("outcome") in {"imported", "kept"}
        for item in files
    )
