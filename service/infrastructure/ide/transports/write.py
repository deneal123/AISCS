"""Protected bounded mutation RPC. Never retry or expose private diagnostics."""

import asyncio
import base64
import hashlib
from typing import Any
from uuid import UUID

import httpx

from service.infrastructure.sidecar import SidecarError
from service.services.chat.domain.ide.edits import EDIT_ERRORS, IdeEditError
from service.services.chat.domain.ide.files import MAX_READ_BYTES, validate_path
from service.services.chat.domain.ide.runtime import WorkspaceBinding
from service.services.files.application.library_read import MAX_LIBRARY_COPY_BYTES


async def write_repository(
    client: Any,
    user_id: UUID,
    binding: WorkspaceBinding,
    *,
    path: str,
    operation: str,
    content: str | bytes,
    expected_digest: str | None,
    capability: str,
    fence: int,
) -> dict[str, Any]:
    path = validate_path(path)
    try:
        if operation == "import" and isinstance(content, bytes):
            raw = content
        elif isinstance(content, str):
            raw = content.encode("utf-8")
        else:
            raise IdeEditError("ide_file_unsupported")
    except (AttributeError, UnicodeError):
        raise IdeEditError("ide_file_unsupported") from None
    if len(raw) > (MAX_LIBRARY_COPY_BYTES if operation == "import" else MAX_READ_BYTES):
        raise IdeEditError("ide_write_limit")
    if operation not in {"file", "directory", "import"} or (operation != "import" and b"\0" in raw):
        raise IdeEditError("ide_file_unsupported")
    if operation == "import" and (type(content) is not bytes or expected_digest is not None):
        raise IdeEditError("ide_file_unsupported")
    if operation == "directory" and (raw or expected_digest is not None):
        raise IdeEditError("ide_file_unsupported")
    if not client.enabled:
        raise IdeEditError()
    endpoint = "import" if operation == "import" else "write"
    try:
        async with asyncio.timeout(12):
            result = await client._client.request_json(
                "POST",
                f"/workspaces/{binding.workspace_id}/ide/{endpoint}",
                timeout=12,
                json_body={
                    "user_id": str(user_id),
                    "token": binding.token,
                    "path": path,
                    "operation": operation,
                    "content": base64.b64encode(raw).decode("ascii")
                    if operation == "import"
                    else content,
                    **(
                        {"sha256": hashlib.sha256(raw).hexdigest()} if operation == "import" else {}
                    ),
                    "expected_digest": expected_digest,
                    "coordination_capability": capability,
                    "coordination_fence": fence,
                },
            )
    except SidecarError as error:
        raise IdeEditError(
            error.code if error.code in EDIT_ERRORS else "ide_write_unconfirmed"
        ) from None
    except (TimeoutError, httpx.HTTPError, ValueError, TypeError):
        raise IdeEditError("ide_write_unconfirmed") from None
    expected = dict(
        written=True,
        path=path,
        kind="dir" if operation == "directory" else "file",
        size=0 if operation == "directory" else len(raw),
        digest=None if operation == "directory" else hashlib.sha256(raw).hexdigest(),
    )
    if (
        type(result) is not dict
        or type(result.get("written")) is not bool
        or type(result.get("size")) is not int
        or result != expected
    ):
        raise IdeEditError("ide_write_unconfirmed")
    return expected
