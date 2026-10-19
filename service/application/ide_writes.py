"""Bounded private writer, serialized by the route's operation/coordination owners."""

from __future__ import annotations

import hashlib
import io
import json
import time

from infrastructure import ide_read_runtime, ide_write_runtime

from application.ide_bundles import program_source
from drivers.binary_exec import BinaryExecFailure

WRITE_ERRORS = frozenset(
    {
        "ide_path_forbidden",
        "ide_file_changed",
        "ide_file_missing",
        "ide_file_unsupported",
        "ide_write_limit",
        "ide_runtime_expired",
        "invalid_request",
        "ide_write_unconfirmed",
    }
)


class IdeWriteFailure(Exception):
    def __init__(self, code="ide_write_unconfirmed"):
        self.code = code if type(code) is str and code in WRITE_ERRORS else "ide_write_unconfirmed"
        super().__init__(self.code)


class IdeWriteService:
    def __init__(self, driver):
        self.driver = driver

    async def write(self, item, *, path, operation, content, expected_digest):
        try:
            ide_read_runtime.components(path)
            if operation == "import":
                if type(content) is not bytes or expected_digest is not None:
                    raise IdeWriteFailure("invalid_request")
                raw = content
            else:
                raw = content.encode("utf-8")
            limit = (
                ide_write_runtime.MAX_IMPORT_BYTES
                if operation == "import"
                else ide_read_runtime.MAX_BYTES
            )
            if len(raw) > limit:
                raise IdeWriteFailure("ide_write_limit")
        except (ide_read_runtime.ReadFailure, UnicodeError):
            raise IdeWriteFailure("ide_path_forbidden") from None
        request = dict(
            root=item.policy.root,
            path=path,
            operation=operation,
            expected_digest=expected_digest,
            deadline=item.expires_at,
            input_size=len(raw),
            input_sha256=hashlib.sha256(raw).hexdigest(),
        )
        helper = program_source(
            extra_modules=(ide_read_runtime, ide_write_runtime),
            entrypoint="infrastructure.ide_write_runtime",
        )
        try:
            with io.BytesIO(raw) as source:
                async with self.driver.exec_binary(
                    item.ref,
                    helper,
                    header=json.dumps(request).encode() + b"\n",
                    source=source,
                    input_size=len(raw),
                    output_limit=4096,
                    timeout=max(0.1, min(10, item.expires_at - time.time())),
                ) as reply:
                    if (
                        reply.exit_code
                        or reply.diagnostic != b'{"status":"ok","operation":"write"}'
                    ):
                        raise IdeWriteFailure()
                    result = json.loads(reply.source.read(4097))
                    if type(result) is not dict:
                        raise IdeWriteFailure()
                    if "error" in result:
                        raise IdeWriteFailure(result["error"])
                    expected = dict(
                        written=True,
                        path=path,
                        kind="dir" if operation == "directory" else "file",
                        digest=None
                        if operation == "directory"
                        else hashlib.sha256(raw).hexdigest(),
                        size=0 if operation == "directory" else len(raw),
                    )
                    if (
                        type(result.get("written")) is not bool
                        or type(result.get("size")) is not int
                        or result != expected
                    ):
                        raise IdeWriteFailure()
                    return result
        except (BinaryExecFailure, ValueError, TypeError, AttributeError):
            raise IdeWriteFailure() from None
