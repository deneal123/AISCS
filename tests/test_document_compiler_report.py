"""Compiler report admission never truncates, coerces or exposes private bodies."""

import json
from unittest.mock import AsyncMock

import pytest
from infrastructure import document_compiler


def ready_report():
    return {
        "status": "ready",
        "failure_code": "",
        "diagnostics": [],
        "page_count": 1,
        "page_width_pt": 595.0,
        "page_height_pt": 842.0,
        "artifact": {"filename": "document.pdf", "size": 100, "sha256": "a" * 64},
    }


@pytest.mark.parametrize(
    "diagnostics",
    [
        None,
        {},
        ["private-body"],
        [{"severity": "error", "code": "pdf_invalid"}],
        [{"severity": "private-severity"}],
        [{"severity": []}],
        [{"severity": "warning", "count": "private-count"}],
        [{"severity": "info", "count": True}],
    ],
    ids=[
        "absent",
        "object",
        "scalar_item",
        "blocking",
        "unknown",
        "invalid_type",
        "string_count",
        "bool_count",
    ],
)
def test_ready_cannot_hide_blocking_or_invalid_diagnostics(diagnostics):
    from infrastructure.document_report import ready_artifacts_valid

    report = ready_report() | {"diagnostics": diagnostics}
    assert not ready_artifacts_valid(report, final=False, artifact_limit=1024, visual_limit=256)


def test_ready_preserves_nonblocking_diagnostics():
    from infrastructure.document_report import ready_artifacts_valid

    report = ready_report() | {
        "diagnostics": [
            {"severity": "warning", "code": "overfull_box", "count": 2},
            {"severity": "info", "code": "latex_lint"},
        ]
    }
    assert ready_artifacts_valid(report, final=False, artifact_limit=1024, visual_limit=256)


@pytest.mark.parametrize(
    "change",
    [
        {"visual_bundle": None},
        {"page_count": 201},
        {"visual_bundle": {"size": 1, "sha256": "b" * 64, "page_count": 2}},
        {"visual_bundle": {"size": 257, "sha256": "b" * 64, "page_count": 1}},
        {"visual_bundle": {"size": 1, "sha256": "b" * 64, "page_count": True}},
    ],
    ids=["missing_visual", "page_limit", "page_mismatch", "visual_size", "bool_visual_pages"],
)
def test_final_requires_bounded_matching_visual_inventory(change):
    from infrastructure.document_report import ready_artifacts_valid

    report = ready_report() | change
    assert not ready_artifacts_valid(report, final=True, artifact_limit=1024, visual_limit=256)


def test_valid_preview_and_final_inventory_preserve_exact_limits():
    from infrastructure.document_report import ready_artifacts_valid

    report = ready_report()
    assert ready_artifacts_valid(report, final=False, artifact_limit=100, visual_limit=256)
    assert not ready_artifacts_valid(report, final=False, artifact_limit=99, visual_limit=256)
    report["visual_bundle"] = {"size": 256, "sha256": "b" * 64, "page_count": 1}
    assert ready_artifacts_valid(report, final=True, artifact_limit=100, visual_limit=256)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("artifact", None),
        ("artifact", {"filename": "../private.pdf", "size": 100, "sha256": "a" * 64}),
        ("artifact", {"filename": "document.pdf", "size": True, "sha256": "a" * 64}),
        ("artifact", {"filename": "document.pdf", "size": 100, "sha256": "private-marker"}),
        ("page_count", True),
        ("page_count", 0),
        ("page_width_pt", "595"),
        ("page_height_pt", -1),
        ("source_bundle", []),
    ],
    ids=[
        "missing_pdf",
        "path",
        "bool_size",
        "hash",
        "bool_pages",
        "no_pages",
        "string_geometry",
        "negative_geometry",
        "malformed_optional",
    ],
)
async def test_incomplete_ready_report_cannot_start_publication(monkeypatch, field, value):
    report = ready_report()
    report[field] = value
    monkeypatch.setattr(
        document_compiler,
        "_command",
        AsyncMock(
            side_effect=[(0, b""), (0, json.dumps(report).encode())],
        ),
    )
    result = await document_compiler.DockerDocumentCompiler().execute(
        document_compiler.PreparedCompilerJob("job", "compiler", "project"),
        entrypoint="main.tex",
        engine="xelatex",
        final=False,
    )
    assert (result.status, result.failure_code, result.report) == (
        "failed",
        "runtime_unavailable",
        {},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        b"[]",
        b"null",
        b'"private-report-marker"',
        b"7",
        b'{"status":"private-report-marker"}',
        b'{"status":"failed","failure_code":"private-report-marker"}',
        b'{"status":"failed","failure_code":[]}',
        b'{"status":"ready","value":NaN}',
        b'{"status":"failed","status":"ready"}',
        b'{"status":"ready"}' + b" " * 262144 + b"private-report-marker",
    ],
    ids=[
        "array",
        "null",
        "string",
        "integer",
        "unknown_status",
        "unknown_failure",
        "invalid_failure_type",
        "nan",
        "duplicate_status",
        "oversized_prefix",
    ],
)
async def test_invalid_report_is_bounded_and_not_returned(monkeypatch, payload):
    command = AsyncMock(side_effect=[(0, b""), (0, payload)])
    monkeypatch.setattr(document_compiler, "_command", command)
    result = await document_compiler.DockerDocumentCompiler().execute(
        document_compiler.PreparedCompilerJob("job", "compiler", "project"),
        entrypoint="main.tex",
        engine="xelatex",
        final=False,
    )
    assert (result.status, result.failure_code, result.report) == (
        "failed",
        "runtime_unavailable",
        {},
    )
    assert command.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,status,failure",
    [(0, "ready", ""), (1, "failed", "compile_failed"), (0, "failed", "audit_failed")],
)
async def test_trusted_report_retains_status_and_bounded_diagnostics(
    monkeypatch, code, status, failure
):
    report = {"status": status, "failure_code": failure, "diagnostics": []}
    if status == "ready":
        report = ready_report()
    monkeypatch.setattr(
        document_compiler,
        "_command",
        AsyncMock(
            side_effect=[
                (code, b""),
                (0, json.dumps(report).encode()),
            ]
        ),
    )
    result = await document_compiler.DockerDocumentCompiler().execute(
        document_compiler.PreparedCompilerJob("job", "compiler", "project"),
        entrypoint="main.tex",
        engine="xelatex",
        final=False,
    )
    assert (result.status, result.failure_code, result.report) == (status, failure, report)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"status":"ready","value":1e999}',
        b'{"status":"ready","nested":{"a":1,"a":2}}',
        b'{"status":"ready","failure_code":null}',
        b'{"status":"ready"}\xff',
        b"[" * 2000 + b"]" * 2000,
    ],
    ids=["float_overflow", "nested_duplicate", "null_failure", "bad_utf8", "deep_nesting"],
)
def test_invalid_numeric_nested_and_encoding_reports_are_rejected(payload):
    from infrastructure.document_report import parse_report

    assert parse_report(payload, 0) is None


def test_exact_budget_and_exit_status_consistency():
    from infrastructure.document_report import MAX_REPORT_BYTES, parse_report

    value = b'{"status":"ready"}'
    payload = value + b" " * (MAX_REPORT_BYTES - len(value))
    assert parse_report(payload, 0) == {"status": "ready"}
    assert parse_report(payload + b" ", 0) is None
    assert parse_report(value, 1) is None
