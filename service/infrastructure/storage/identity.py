"""Stable private storage namespace, without credentials or public URL settings."""

from __future__ import annotations

import hashlib
import json


def storage_identity(kind: str, *locators: str) -> str:
    if (
        kind not in {"local", "minio"}
        or not locators
        or any(not isinstance(value, str) or not value for value in locators)
    ):
        raise ValueError("storage_identity_invalid")
    value = json.dumps([1, kind, *locators], ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("ascii")).hexdigest()
