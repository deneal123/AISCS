"""Closed metadata scan projection; integration payloads are never wire results."""

import re
from typing import Any

_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_WIRE_SIZE = 2**53 - 1


def safe_scan_result(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    status = value.get("status")
    if status == "ok":
        size, digest = value.get("size"), value.get("sha256")
        if type(size) is not int or not 0 <= size <= _MAX_WIRE_SIZE:
            return None
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            return None
        return {"status": "ok", "size": size, "sha256": digest}
    if status == "error":
        return {"status": "error", "reason": "unavailable"}
    if status == "skipped" and value.get("reason") == "no_download":
        return {"status": "skipped", "reason": "no_download"}
    return None
