"""Bounded atomic file-move RPC. Caller owns both path leases and registry lock."""

import io
import json
import time

from infrastructure import ide_move_runtime, ide_read_runtime

from application.ide_bundles import program_source
from application.ide_writes import IdeWriteFailure
from drivers.binary_exec import BinaryExecFailure


async def move_file(driver, item, *, path, destination, expected_digest):
    try:
        ide_read_runtime.components(path)
        ide_read_runtime.components(destination)
    except ide_read_runtime.ReadFailure:
        raise IdeWriteFailure("ide_path_forbidden") from None
    header = dict(
        root=item.policy.root,
        path=path,
        destination=destination,
        expected_digest=expected_digest,
        deadline=item.expires_at,
    )
    source = program_source(
        extra_modules=(ide_read_runtime, ide_move_runtime),
        entrypoint="infrastructure.ide_move_runtime",
    )
    try:
        with io.BytesIO() as stream:
            async with driver.exec_binary(
                item.ref,
                source,
                header=json.dumps(header).encode() + b"\n",
                source=stream,
                input_size=0,
                output_limit=4096,
                timeout=max(0.1, min(10, item.expires_at - time.time())),
            ) as reply:
                if reply.exit_code or reply.diagnostic != b'{"status":"ok","operation":"move"}':
                    raise IdeWriteFailure()
                result = json.loads(reply.source.read(4097))
                if type(result) is not dict:
                    raise IdeWriteFailure()
                if "error" in result:
                    raise IdeWriteFailure(result["error"])
                if (
                    set(result) != {"moved", "path", "moved_from", "size"}
                    or result["moved"] is not True
                    or result["path"] != destination
                    or result["moved_from"] != path
                    or type(result["size"]) is not int
                    or result["size"] < 0
                ):
                    raise IdeWriteFailure()
                return result
    except (BinaryExecFailure, ValueError, TypeError):
        raise IdeWriteFailure() from None
