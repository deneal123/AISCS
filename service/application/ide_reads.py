"""Read-only sandbox subprocess orchestration, independent of legacy Git snapshots."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from infrastructure import ide_read_runtime as runtime

READ_ERRORS = frozenset(
    {
        "ide_path_forbidden",
        "ide_file_missing",
        "ide_file_changed",
        "ide_file_unsupported",
        "ide_read_unavailable",
        "invalid_request",
    }
)


class IdeReadFailure(Exception):
    def __init__(self, code="ide_read_unavailable"):
        self.code = code if type(code) is str and code in READ_ERRORS else "ide_read_unavailable"
        super().__init__(self.code)


class IdeReadService:
    def __init__(self, run, *, program_source=None):
        self._run = run
        self._source = program_source or Path(runtime.__file__).read_text(encoding="utf-8")

    async def read(self, item, *, operation: str, path: str) -> dict:
        try:
            runtime.components(path, root_allowed=operation == "tree")
        except runtime.ReadFailure as failure:
            raise IdeReadFailure(failure.code) from None
        if operation not in {"tree", "file"}:
            raise IdeReadFailure("invalid_request")
        request = {"root": item.policy.root, "path": path, "operation": operation}
        result = await self._run(
            item,
            "python3 -I -c " + shlex.quote(self._source),
            stdin_payload=json.dumps(request).encode(),
        )
        if result.exit_code or result.truncated or getattr(result, "timed_out", False):
            raise IdeReadFailure()
        try:
            response = json.loads(result.stdout)
            if not isinstance(response, dict):
                raise ValueError
        except (ValueError, TypeError):
            raise IdeReadFailure() from None
        if "error" in response:
            raise IdeReadFailure(response["error"])
        return response
