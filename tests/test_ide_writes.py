import hashlib
import io
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from application.ide_bundles import program_source
from application.ide_writes import IdeWriteFailure, IdeWriteService
from infrastructure import ide_read_runtime, ide_write_runtime


def test_writer_program_is_isolated_bounded_and_contains_no_repository_import():
    source = program_source(
        extra_modules=(ide_read_runtime, ide_write_runtime),
        entrypoint="infrastructure.ide_write_runtime",
    )
    assert len(source.encode()) <= 96 * 1024
    assert "infrastructure.ide_write_runtime" in source
    compile(source, "trusted", "exec")


class Driver:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    @asynccontextmanager
    async def exec_binary(self, ref, helper, **kwargs):
        raw = kwargs["source"].read()
        self.calls.append((ref, json.loads(kwargs["header"]), raw, kwargs))
        body = self.result or {
            "written": True,
            "path": "main.py",
            "kind": "file",
            "digest": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
        }
        yield SimpleNamespace(
            exit_code=0,
            diagnostic=b'{"status":"ok","operation":"write"}',
            source=io.BytesIO(json.dumps(body).encode()),
        )


@pytest.mark.asyncio
async def test_writer_transfers_utf8_on_stdin_and_checks_exact_ack():
    driver = Driver()
    item = SimpleNamespace(
        policy=SimpleNamespace(root="/workspace"), ref="private", expires_at=time.time() + 60
    )
    result = await IdeWriteService(driver).write(
        item, path="main.py", operation="file", content="print('Привет')", expected_digest=None
    )
    assert result["size"] == len("print('Привет')".encode())
    assert driver.calls[0][1]["input_sha256"] == result["digest"]
    assert driver.calls[0][2] == "print('Привет')".encode()
    assert "Привет" not in program_source()
    driver.result = {**result, "path": "different.py"}
    with pytest.raises(IdeWriteFailure, match="ide_write_unconfirmed"):
        await IdeWriteService(driver).write(
            item, path="main.py", operation="file", content="", expected_digest=None
        )


@pytest.mark.asyncio
async def test_import_transfers_opaque_bytes_without_weakening_text_or_overwrite_rules():
    driver = Driver()
    item = SimpleNamespace(
        policy=SimpleNamespace(root="/workspace"), ref="private", expires_at=time.time() + 60
    )
    raw = b"PK\x03\x04\x00\xff" + b"x" * 262144
    result = await IdeWriteService(driver).write(
        item, path="main.py", operation="import", content=raw, expected_digest=None
    )
    assert result["digest"] == hashlib.sha256(raw).hexdigest()
    assert driver.calls[0][2] == raw
    assert driver.calls[0][1]["operation"] == "import"
    for content, digest in [
        (raw, "a" * 64),
        ("text", None),
        (b"x" * (ide_write_runtime.MAX_IMPORT_BYTES + 1), None),
    ]:
        with pytest.raises(IdeWriteFailure):
            await IdeWriteService(driver).write(
                item, path="main.py", operation="import", content=content, expected_digest=digest
            )
    assert len(driver.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["../escape", ".git/config", "a/.gpthub-write-x", "/etc/passwd"])
async def test_invalid_path_cannot_dispatch(path):
    driver = Driver()
    with pytest.raises(IdeWriteFailure):
        await IdeWriteService(driver).write(
            None, path=path, operation="file", content="", expected_digest=None
        )
    assert not driver.calls
