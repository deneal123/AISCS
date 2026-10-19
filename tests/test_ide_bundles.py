import hashlib
import io
import json
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import pytest
from application.ide_bundles import BundleTransferFailure, IdeBundleService, program_source
from infrastructure.ide_bundle_format import BundleFailure, BundleLimits, write_bundle

from drivers.base import DriverError
from drivers.binary_exec import BinaryExecFailure, BinaryExecReply

LIMITS = BundleLimits(16, 1024, 4096, 16384, 8192, 8)
ITEM = SimpleNamespace(
    ref="private_ref", policy=SimpleNamespace(root="/workspace", exec_timeout_sec=10)
)


def capsule():
    @contextmanager
    def source(_entry):
        yield io.BytesIO(b"private code")

    output = io.BytesIO()
    write_bundle(
        [
            dict(
                path="main.py",
                kind="file",
                mode=0o644,
                mtime_ns=0,
                size=12,
                sha256=hashlib.sha256(b"private code").hexdigest(),
            )
        ],
        source,
        output,
        LIMITS,
    )
    return output.getvalue()


class Driver:
    def __init__(self, body, report=None, exit_code=0, failure=None):
        self.body, self.report, self.exit_code, self.failure = body, report, exit_code, failure
        self.calls = []

    @asynccontextmanager
    async def exec_binary(self, ref, program, **kwargs):
        self.calls.append((ref, program, kwargs))
        if self.failure:
            raise self.failure
        with io.BytesIO(self.body) as source:
            yield BinaryExecReply(
                self.exit_code,
                source,
                len(self.body),
                hashlib.sha256(self.body).hexdigest(),
                self.report
                if isinstance(self.report, bytes)
                else json.dumps(self.report, separators=(",", ":")).encode(),
            )


def capture_driver(**changes):
    body = capsule()
    report = dict(
        status="ok", operation="capture", size=len(body), sha256=hashlib.sha256(body).hexdigest()
    )
    report.update(changes)
    return Driver(body, report)


def test_program_is_import_isolated_static_and_below_argument_limit():
    source = program_source()
    compile(source, "trusted-capsule", "exec")
    assert len(source.encode()) <= 96 * 1024
    assert "private code" not in source and "private_ref" not in source


async def test_capture_verifies_bytes_and_preserves_owned_stream_lifetime():
    driver = capture_driver()
    async with IdeBundleService(driver, source="static helper").capture(ITEM, LIMITS) as source:
        assert source.read() == driver.body and not source.closed
    assert source.closed
    ref, program, options = driver.calls[0]
    assert ref == "private_ref" and program == "static helper"
    assert json.loads(options["header"])["operation"] == "capture"
    assert options["source"] is None and options["output_limit"] == LIMITS.archive_bytes


@pytest.mark.parametrize("write", [False, True])
async def test_restore_receipt_has_a_bounded_private_exchange_and_a_runtime_deadline(write):
    import time

    item = SimpleNamespace(ref=ITEM.ref, policy=ITEM.policy, expires_at=time.time() + 3)
    operation = "seal" if write else "receipt"
    driver = Driver(b"", dict(status="ok", operation=operation, ready=True))
    assert await IdeBundleService(driver, source="trusted helper").receipt(
        item, "a" * 64, write=write
    )
    _, program, options = driver.calls[0]
    header = json.loads(options["header"])
    assert header["operation"] == operation and header["ready_receipt"] == "a" * 64
    assert 0 < options["timeout"] <= 3
    assert options["source"] is None and options["output_limit"] == 0
    assert "a" * 64 not in program


async def test_expired_restore_does_not_dispatch_a_completion_marker():
    item = SimpleNamespace(ref=ITEM.ref, policy=ITEM.policy, expires_at=1)
    driver = Driver(b"", dict(status="ok", operation="seal", ready=True))
    with pytest.raises(BundleFailure):
        await IdeBundleService(driver).receipt(item, "a" * 64, write=True)
    assert not driver.calls


async def test_consistent_transport_hash_does_not_replace_capsule_verification():
    body = b"not a repository capsule"
    driver = Driver(
        body,
        dict(
            status="ok",
            operation="capture",
            size=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
        ),
    )
    with pytest.raises(BundleFailure):
        async with IdeBundleService(driver, source="static").capture(ITEM, LIMITS):
            pytest.fail("invalid capsule exposed")


async def test_ambiguous_duplicate_ack_fields_are_rejected():
    driver = Driver(
        b"",
        b'{"status":"error","code":"ide_bundle_busy","code":"ide_bundle_invalid"}',
        exit_code=65,
    )
    with pytest.raises(BundleFailure, match="ide_bundle_unavailable"):
        async with IdeBundleService(driver, source="static").capture(ITEM, LIMITS):
            pass


async def test_consumer_failure_does_not_fabricate_an_uncertain_helper():
    failure = DriverError("fixture consumer failure")
    with pytest.raises(DriverError) as caught:
        async with IdeBundleService(capture_driver(), source="static").capture(
            ITEM, LIMITS
        ) as source:
            raise failure
    assert caught.value is failure and source.closed


@pytest.mark.parametrize(
    "changes",
    [
        {"size": True},
        {"size": 0},
        {"sha256": "0" * 64},
        {"operation": "restore"},
        {"extra": "ignored"},
    ],
)
async def test_capture_rejects_inconsistent_or_ambiguous_ack(changes):
    with pytest.raises(BundleFailure):
        async with IdeBundleService(capture_driver(**changes), source="static").capture(
            ITEM, LIMITS
        ):
            pytest.fail("unverified bytes exposed")


async def test_restore_validates_published_identity_before_dispatch():
    body = capsule()
    driver = Driver(b"", dict(status="ok", operation="restore", entries=1))
    service = IdeBundleService(driver, source="static")
    digest = hashlib.sha256(body).hexdigest()
    for size, sha in [(len(body) + 1, digest), (len(body), "0" * 64)]:
        with pytest.raises(BundleFailure):
            await service.restore(
                ITEM, io.BytesIO(body), LIMITS, expected_size=size, expected_sha256=sha
            )
    assert driver.calls == []
    assert (
        await service.restore(
            ITEM, io.BytesIO(body), LIMITS, expected_size=len(body), expected_sha256=digest
        )
        == 1
    )
    assert driver.calls[0][2]["output_limit"] == 0
    assert json.loads(driver.calls[0][2]["header"])["input_sha256"] == digest


@pytest.mark.parametrize("count", [True, -1, 0, 2])
async def test_restore_ack_must_match_the_verified_manifest(count):
    body = capsule()
    driver = Driver(b"", dict(status="ok", operation="restore", entries=count))
    with pytest.raises(BundleFailure):
        await IdeBundleService(driver, source="static").restore(
            ITEM,
            io.BytesIO(body),
            LIMITS,
            expected_size=len(body),
            expected_sha256=hashlib.sha256(body).hexdigest(),
        )


async def test_corrupted_input_and_missing_capability_never_fallback():
    driver = capture_driver()
    with pytest.raises(BundleFailure):
        await IdeBundleService(driver, source="static").restore(
            ITEM, io.BytesIO(b"not a capsule"), LIMITS, expected_size=13, expected_sha256="a" * 64
        )
    assert not driver.calls
    with pytest.raises(BundleFailure, match="ide_bundle_unsupported"):
        async with IdeBundleService(object(), source="static").capture(ITEM, LIMITS):
            pass


@pytest.mark.parametrize("settled", [False, True])
async def test_unknown_transfer_preserves_private_liveness_evidence(settled):
    failure = BinaryExecFailure("PRIVATE_ERROR")
    failure.settled = settled
    with pytest.raises(BundleTransferFailure) as caught:
        async with IdeBundleService(Driver(b"", failure=failure), source="static").capture(
            ITEM, LIMITS
        ):
            pass
    assert caught.value.settled is settled
    assert str(caught.value) == "ide_bundle_unavailable"


@pytest.mark.parametrize(
    "report",
    [
        dict(status="error", code="ide_bundle_target_not_empty"),
        dict(status="error", code="PRIVATE_DATA"),
        [],
    ],
)
async def test_worker_errors_never_expose_private_diagnostics(report):
    with pytest.raises(BundleFailure) as caught:
        async with IdeBundleService(Driver(b"", report, exit_code=65), source="static").capture(
            ITEM, LIMITS
        ):
            pass
    assert "PRIVATE" not in str(caught.value)
