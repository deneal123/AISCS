"""Owned semantic edits rendered privately, then committed by the existing source writer."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

from fastapi import HTTPException

from service.infrastructure.agents_client.sidecar_tools import _client
from service.infrastructure.sidecar import SidecarBadRequest, SidecarError


async def render_owned_edit(client: Any, ref: dict, payload: Any, config: Any) -> dict:
    project = await client.document_project_status(ref, path=payload.path)
    if not isinstance(project, dict):
        raise HTTPException(status_code=404, detail="document_project_not_found")
    if (
        project.get("revision") != payload.expected_revision
        or project.get("authoring_version") != payload.authoring_version
        or project.get("draft_digest") != payload.draft_digest
        or (
            payload.expected_source_digest is not None
            and project.get("source_digest") != payload.expected_source_digest
        )
    ):
        raise HTTPException(status_code=409, detail="source_changed")
    manifest_file = (
        await client.read_file(ref, f"{payload.path}/.gpthub-authoring.json")
        if payload.authoring_version
        else None
    )
    try:
        manifest = json.loads((manifest_file or {}).get("content", "{}"))
        paths = list(manifest["block_files"]) if payload.authoring_version else []
        if payload.authoring_version and not 1 <= len(paths) <= 120:
            raise ValueError
        for path in paths:
            parts = PurePosixPath(path).parts
            if not path.startswith("content/") or ".." in parts or "\\" in path:
                raise ValueError
    except (ValueError, TypeError, KeyError):
        raise HTTPException(status_code=422, detail="authoring_invalid") from None
    files = {".gpthub-authoring.json": str(manifest_file["content"])} if manifest_file else {}
    size = sum(len(content.encode()) for content in files.values())
    for path in [
        "main.tex",
        *(["bibliography/references.bib", *paths] if payload.authoring_version else []),
    ]:
        read = await client.read_file(ref, f"{payload.path}/{path}")
        if not isinstance(read, dict) or read.get("truncated"):
            raise HTTPException(status_code=422, detail="authoring_invalid")
        content = str(read.get("content") or "")
        size += len(content.encode())
        if size > 2_000_000:
            raise HTTPException(status_code=413, detail="source_too_large")
        files[path] = content
    try:
        result = await _client(config, 30).request_json(
            "POST",
            "/document-editor/render",
            json_body={
                "files": files,
                "draft": payload.draft,
                "authoring_version": payload.authoring_version,
                "draft_digest": payload.draft_digest,
                "project": project if not payload.authoring_version else None,
            },
        )
    except SidecarBadRequest as exc:
        if exc.code in {"http_409", "source_changed"}:
            raise HTTPException(status_code=409, detail="source_changed") from None
        raise HTTPException(status_code=422, detail="authoring_invalid") from None
    except SidecarError:
        raise HTTPException(status_code=503, detail="document_editor_unavailable") from None
    if not isinstance(result, dict) or not isinstance(result.get("files"), dict):
        raise HTTPException(status_code=503, detail="document_editor_unavailable")
    result["expected_source_digest"] = project.get("source_digest")
    return result
