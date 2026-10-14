"""Unknown Docker state cannot authorize destructive compiler reconciliation."""

import json
from unittest.mock import AsyncMock

import pytest
from infrastructure import document_compiler
from infrastructure.document_compiler import CompilerFailure, DockerDocumentCompiler

_ID = "a" * 64


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "inventory,expected",
    [(b"", True), (_ID.encode(), False), (b"b" * 64, True), (b"malformed", False)],
)
async def test_failed_remove_is_success_only_after_proven_absence(monkeypatch, inventory, expected):
    command = AsyncMock(side_effect=[(1, b""), (0, inventory)])
    monkeypatch.setattr(document_compiler, "_command", command)
    compiler = DockerDocumentCompiler()
    assert await compiler.destroy(_ID) is expected
    assert compiler.cleanup_failures == int(not expected)
    assert command.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [(1, b""), CompilerFailure("timeout"), OSError("private-marker")]
)
async def test_inventory_failure_is_not_proof_of_removed_compiler(monkeypatch, failure):
    monkeypatch.setattr(document_compiler, "_command", AsyncMock(side_effect=[(1, b""), failure]))
    compiler = DockerDocumentCompiler()
    assert await compiler.destroy(_ID) is False
    assert compiler.cleanup_failures == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["labels", "state", "timeout", "null", "array", "bad_state", "bad_expiry"]
)
async def test_uncertain_inspection_does_not_destroy_a_potentially_live_job(monkeypatch, fault):
    async def command(*args, **_kwargs):
        if args[1:3] == ("ps", "-aq"):
            return 0, _ID.encode()
        if args[1:3] == ("inspect", "--format"):
            if fault == "timeout":
                raise CompilerFailure("timeout")
            if "Labels" in args[3]:
                if fault == "labels":
                    return 1, b""
                if fault in {"null", "array"}:
                    return 0, b"null" if fault == "null" else b"[]"
                if fault == "bad_expiry":
                    return 0, b'{"gpthub.document.expires_at":"NaN"}'
                return 0, json.dumps({"gpthub.document.expires_at": "9999999999"}).encode()
            if fault == "state":
                return 1, b""
            return 0, b"unrecognized" if fault == "bad_state" else b"true"
        raise AssertionError("unexpected destructive command")

    monkeypatch.setattr(document_compiler, "_command", command)
    compiler = DockerDocumentCompiler()
    compiler.destroy = AsyncMock(return_value=True)
    assert await compiler.reconcile() == 0
    compiler.destroy.assert_not_awaited()
    assert compiler.cleanup_failures == 1


@pytest.mark.asyncio
async def test_inventory_outage_is_visible_without_authorizing_removal(monkeypatch):
    monkeypatch.setattr(document_compiler, "_command", AsyncMock(return_value=(1, b"")))
    compiler = DockerDocumentCompiler()
    compiler.destroy = AsyncMock()
    assert await compiler.reconcile() == 0
    assert compiler.cleanup_failures == 1
    compiler.destroy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("running", [True, False])
@pytest.mark.parametrize("expiry", [None, "", "0", "-1", True, 1, "1.0", " 1 ", "1e2"])
async def test_unknown_expiry_never_authorizes_compiler_removal(monkeypatch, running, expiry):
    labels = {} if expiry is None else {"gpthub.document.expires_at": expiry}

    async def command(*args, **_kwargs):
        if args[1:3] == ("ps", "-aq"):
            return 0, _ID.encode()
        if "Labels" in args[3]:
            return 0, json.dumps(labels).encode()
        return 0, b"true" if running else b"false"

    monkeypatch.setattr(document_compiler, "_command", command)
    compiler = DockerDocumentCompiler()
    compiler.destroy = AsyncMock(return_value=True)
    assert await compiler.reconcile() == 0
    compiler.destroy.assert_not_awaited()
    assert compiler.cleanup_failures == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "inventory", [b"compiler-name", b"--help", b"\xff", (_ID + "\n" + _ID).encode()]
)
async def test_malformed_inventory_cannot_dispatch_inspection_or_removal(monkeypatch, inventory):
    command = AsyncMock(return_value=(0, inventory))
    monkeypatch.setattr(document_compiler, "_command", command)
    compiler = DockerDocumentCompiler()
    compiler.destroy = AsyncMock(return_value=True)
    with pytest.raises(CompilerFailure, match="^runtime_unavailable$"):
        await compiler.reconcile()
    command.assert_awaited_once()
    compiler.destroy.assert_not_awaited()
    assert compiler.cleanup_failures == 1
