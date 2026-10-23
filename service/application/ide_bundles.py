"""Private sandbox/capsule bridge; not exposed until lifecycle/lease integration.

Caller owns authorization, generation, quiescence and source/destination lifetime.
Restore is ONLY for a fresh unpublished allocation; any failure/cancellation must
retire it, never issue ready or retry over partial contents. No legacy fallback.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from infrastructure import (
    ide_bundle_files,
    ide_bundle_format,
    ide_bundle_runtime,
    ide_idle,
    ide_restore_receipt,
)
from infrastructure.ide_bundle_format import BundleFailure, BundleLimits, read_bundle

from drivers.base import DriverError
from drivers.binary_exec import BinaryExecFailure, BinaryExecReply, native_io


class BundleTransferFailure(BundleFailure):
    """Private liveness evidence; uncertain restore must retire its destination."""

    def __init__(self, settled: bool) -> None:
        self.settled = settled
        super().__init__("ide_bundle_unavailable")


@dataclass(frozen=True, slots=True)
class CapturedBundle:
    source: BinaryIO = field(repr=False)
    size: int
    sha256: str = field(repr=False)
    entries: int


def program_source(*, extra_modules: tuple = (), entrypoint: str | None = None) -> str:
    sources = {
        f"infrastructure.{module.__name__.rsplit('.', 1)[-1]}": Path(module.__file__).read_text(
            encoding="utf-8"
        )
        for module in (
            ide_bundle_format,
            ide_bundle_files,
            ide_restore_receipt,
            ide_idle,
            ide_bundle_runtime,
            *extra_modules,
        )
    }
    return (
        "import sys,types\n"
        "_package=types.ModuleType('infrastructure');_package.__path__=[]\n"
        "sys.modules['infrastructure']=_package\n"
        f"_sources={sources!r}\n"
        "for _name,_source in _sources.items():\n"
        " _module=types.ModuleType(_name);_module.__file__='/trusted-capsule/'+_name+'.py'\n"
        " sys.modules[_name]=_module\n"
        " exec(compile(_source,_module.__file__,'exec'),_module.__dict__)\n"
        f"sys.modules[{entrypoint or 'infrastructure.ide_bundle_runtime'!r}].main()\n"
    )


def _verify(source: BinaryIO, limits: BundleLimits) -> tuple[int, str, int]:
    with read_bundle(source, limits) as (entries, _archive):
        count = len(entries)
    source.seek(0)
    size, digest = 0, hashlib.sha256()
    while chunk := source.read(65536):
        size += len(chunk)
        if size > limits.archive_bytes:
            raise BundleFailure("ide_bundle_limit")
        digest.update(chunk)
    source.seek(0)
    return size, digest.hexdigest(), count


def _report(reply: BinaryExecReply, operation: str) -> dict[str, Any]:
    try:
        body = json.loads(reply.diagnostic)
        if type(body) is not dict:
            raise ValueError
        if json.dumps(body, separators=(",", ":")).encode() != reply.diagnostic:
            raise ValueError  # Reject duplicate keys/noncanonical private protocol.
        if reply.exit_code:
            if set(body) == {"status", "code"} and body["status"] == "error":
                raise BundleFailure(body["code"])
            raise ValueError
        if body.get("status") != "ok" or body.get("operation") != operation:
            raise ValueError
        return body
    except BundleFailure:
        raise
    except (ValueError, TypeError, KeyError):
        raise BundleFailure("ide_bundle_unavailable") from None


class IdeBundleService:
    def __init__(self, driver: Any, *, source: str | None = None) -> None:
        self.driver, self.program = driver, source or program_source()

    def _exchange(
        self,
        item: Any,
        operation: str,
        limits: BundleLimits,
        source: BinaryIO | None = None,
        size: int = 0,
        digest: str | None = None,
        *,
        ready_receipt: str | None = None,
        idle_supervisor: dict | None = None,
    ) -> AbstractAsyncContextManager[BinaryExecReply]:
        run = getattr(self.driver, "exec_binary", None)
        if not callable(run):
            raise BundleFailure("ide_bundle_unsupported")
        timeout = min(30.0, float(item.policy.exec_timeout_sec))
        if ready_receipt is not None:
            timeout = min(timeout, item.expires_at - time.time())
            if not math.isfinite(timeout) or timeout <= 0 or item.policy.root != "/workspace":
                raise BundleFailure("ide_bundle_unavailable")
        header = (
            json.dumps(
                dict(
                    root=item.policy.root,
                    operation=operation,
                    limits=asdict(limits),
                    input_size=size,
                    input_sha256=digest,
                    timeout=timeout,
                    **({"ready_receipt": ready_receipt} if ready_receipt is not None else {}),
                    **({"idle_supervisor": idle_supervisor} if idle_supervisor is not None else {}),
                ),
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        return run(
            item.ref,
            self.program,
            header=header,
            source=source,
            input_size=size,
            output_limit=limits.archive_bytes if operation == "capture" else 0,
            timeout=timeout,
        )

    async def receipt(self, item: Any, proof: str, *, write: bool) -> bool:
        if (
            type(proof) is not str
            or len(proof) != 64
            or any(c not in "0123456789abcdef" for c in proof)
        ):
            raise BundleFailure()
        operation = "seal" if write else "receipt"
        # Metadata-only helper: no repository bytes or quota/retention policy.
        limits = BundleLimits(1, 1, 1, 4096, 1024, 1)
        try:
            async with self._exchange(item, operation, limits, ready_receipt=proof) as reply:
                body = _report(reply, operation)
                if (
                    set(body) != {"status", "operation", "ready"}
                    or reply.size != 0
                    or type(body["ready"]) is not bool
                ):
                    raise BundleFailure()
                return body["ready"]
        except BinaryExecFailure as failure:
            raise BundleTransferFailure(failure.settled) from None
        except DriverError:
            raise BundleTransferFailure(False) from None

    @asynccontextmanager
    async def capture(self, item: Any, limits: BundleLimits) -> AsyncIterator[BinaryIO]:
        async with self.capture_verified(item, limits) as capture:
            yield capture.source

    @asynccontextmanager
    async def capture_verified(
        self, item: Any, limits: BundleLimits, *, idle_supervisor: dict | None = None
    ) -> AsyncIterator[CapturedBundle]:
        async with AsyncExitStack() as resources:
            try:
                reply = await resources.enter_async_context(
                    self._exchange(item, "capture", limits, idle_supervisor=idle_supervisor)
                )
            except BinaryExecFailure as failure:
                raise BundleTransferFailure(failure.settled) from None
            except DriverError:
                raise BundleTransferFailure(False) from None
            body = _report(reply, "capture")
            if (
                set(body) != {"status", "operation", "size", "sha256"}
                or type(body["size"]) is not int
                or body["size"] != reply.size
                or body["sha256"] != reply.sha256
            ):
                raise BundleFailure()
            verified = await native_io(_verify, reply.source, limits)
            if verified[:2] != (reply.size, reply.sha256):
                raise BundleFailure()
            # A consumer's storage/DB failure is not a transfer liveness failure.
            yield CapturedBundle(reply.source, *verified)

    async def restore(
        self,
        item: Any,
        source: BinaryIO,
        limits: BundleLimits,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> int:
        # Before dispatch; expected values come from the owned published record.
        verified = await native_io(_verify, source, limits)
        if type(expected_size) is not int or verified[:2] != (expected_size, expected_sha256):
            raise BundleFailure()
        try:
            async with self._exchange(
                item, "restore", limits, source, expected_size, expected_sha256
            ) as reply:
                body = _report(reply, "restore")
                if (
                    set(body) != {"status", "operation", "entries"}
                    or reply.size != 0
                    or type(body["entries"]) is not int
                    or body["entries"] != verified[2]
                ):
                    raise BundleFailure()
                return body["entries"]
        except BinaryExecFailure as failure:
            raise BundleTransferFailure(failure.settled) from None
        except DriverError:
            raise BundleTransferFailure(False) from None
