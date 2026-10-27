"""Read project-owned registered bibliography without provisioning or paid work."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from service.infrastructure.agents_client.sidecar_tools import _client
from service.infrastructure.sidecar import SidecarBadRequest, SidecarError


class RegisteredSource(BaseModel):
    source_id: int = Field(strict=True, ge=1, le=10_000)
    title: str | None = Field(default=None, strict=True, max_length=2000)
    author: str | None = Field(default=None, strict=True, max_length=2000)
    year: str | None = Field(default=None, strict=True, max_length=2000)
    url: str | None = Field(default=None, strict=True, max_length=2000)
    doi: str | None = Field(default=None, strict=True, max_length=2000)


class SourceInventory(BaseModel):
    sources: list[RegisteredSource] = Field(max_length=10_000)
    unresolved_count: int = Field(strict=True, ge=0, le=10_000)


async def read_owned_sources(client: Any, ref: dict, path: str, config: Any) -> dict:
    if (
        PurePosixPath(path).is_absolute()
        or ".." in PurePosixPath(path).parts
        or "\\" in path
        or "\x00" in path
    ):
        raise HTTPException(status_code=422, detail="document_path_invalid")
    project = await client.document_project_status(ref, path=path)
    if not isinstance(project, dict) or project.get("path") != path:
        raise HTTPException(status_code=404, detail="document_project_not_found")
    read = await client.read_file(ref, f"{path}/bibliography/references.bib")
    if (
        not isinstance(read, dict)
        or read.get("truncated")
        or not isinstance(read.get("content"), str)
    ):
        raise HTTPException(status_code=422, detail="bibliography_unavailable")
    if len(read["content"].encode("utf-8")) > 750_000:
        raise HTTPException(status_code=413, detail="bibliography_too_large")
    try:
        result = await _client(config, 15).request_json(
            "POST", "/document-editor/sources", json_body={"bibliography": read["content"]}
        )
    except SidecarBadRequest:
        raise HTTPException(status_code=422, detail="bibliography_invalid") from None
    except SidecarError:
        raise HTTPException(status_code=503, detail="document_sources_unavailable") from None
    latest = await client.document_project_status(ref, path=path)
    if not isinstance(latest, dict) or any(
        latest.get(field) != project.get(field)
        for field in ("path", "revision", "source_digest", "authoring_version", "draft_digest")
    ):
        raise HTTPException(status_code=409, detail="source_changed")
    try:
        result = SourceInventory.model_validate(result).model_dump(exclude_none=True)
    except ValidationError:
        raise HTTPException(status_code=503, detail="document_sources_unavailable") from None
    return {
        **result,
        "revision": project["revision"],
        "source_digest": project.get("source_digest"),
    }
