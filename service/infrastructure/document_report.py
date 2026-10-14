"""Bounded admission of compiler reports; no truncation or error-body projection."""

import json
import math
import re

MAX_REPORT_BYTES = 262144
COMPILER_FAILURE_CODES = frozenset(
    {
        "compile_failed",
        "invalid_project",
        "artifact_too_large",
        "audit_failed",
        "visual_render_failed",
        "build_timeout",
        "internal",
    }
)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid_report")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("invalid_report")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("invalid_report")
    return number


def parse_report(payload: bytes, exit_code: int) -> dict | None:
    if not payload or len(payload) > MAX_REPORT_BYTES:
        return None
    try:
        report = json.loads(
            payload,
            object_pairs_hook=_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (UnicodeError, ValueError, RecursionError):
        return None
    if not isinstance(report, dict):
        return None
    status = report.get("status")
    if not isinstance(status, str) or status not in {"ready", "failed"}:
        return None
    failure = report.get("failure_code", "" if status == "ready" else "compile_failed")
    if not isinstance(failure, str):
        return None
    if status == "ready":
        if exit_code != 0 or failure:
            return None
    elif failure not in COMPILER_FAILURE_CODES:
        return None
    return report


def _artifact(value: object, limit: int, filename: str | None = None) -> bool:
    if not isinstance(value, dict):
        return False
    size = value.get("size")
    digest = value.get("sha256")
    return (
        type(size) is int
        and 0 < size <= limit
        and isinstance(digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
        and (filename is None or value.get("filename") == filename)
    )


def ready_artifacts_valid(
    report: dict, *, final: bool, artifact_limit: int, visual_limit: int
) -> bool:
    """Validate facts before transfer; physical hashes are checked again after it."""
    diagnostics = report.get("diagnostics")
    if not isinstance(diagnostics, list):
        return False
    for item in diagnostics:
        if not isinstance(item, dict):
            return False
        severity = item.get("severity")
        if not isinstance(severity, str) or severity not in {"info", "warning"}:
            return False
        count = item.get("count", 1)
        if type(count) is not int or count < 1:
            return False
    pages = report.get("page_count")
    if type(pages) is not int or pages < 1 or (final and pages > 200):
        return False
    for field in ("page_width_pt", "page_height_pt"):
        value = report.get(field)
        if type(value) not in (int, float) or value <= 0:
            return False
    if not _artifact(report.get("artifact"), artifact_limit, "document.pdf"):
        return False
    for field, filename in (("source_bundle", "source.zip"), ("preview", None)):
        value = report.get(field)
        if value is not None and not _artifact(value, artifact_limit, filename):
            return False
    visual = report.get("visual_bundle")
    if visual is None:
        return not final
    return (
        _artifact(visual, visual_limit)
        and type(visual.get("page_count")) is int
        and visual["page_count"] == pages
    )
