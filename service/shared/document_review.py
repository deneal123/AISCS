"""Стабильная идентичность неизменяемого private PDF-предложения, без полномочий."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID


def review_proposal_id(path: str, proposal: dict) -> str:
    """Одинаковый запрос имеет тот же ID; версия и область входят в digest."""
    canonical = json.dumps(
        {"path": path, "proposal": proposal},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(b"gpthub-document-review-v1\0" + canonical).hexdigest()[:32]


def operation_build_id(workspace_id: str, operation_id: str) -> str:
    """ID сборки известен до dispatch; повтор HTTP не создаёт новую идентичность."""
    if not isinstance(operation_id, str):
        raise ValueError("invalid operation id")
    canonical = str(UUID(operation_id))
    if canonical != operation_id:
        raise ValueError("invalid operation id")
    return hashlib.sha256(
        ("gpthub-document-build-v1\0" + workspace_id + "\0" + canonical).encode()
    ).hexdigest()[:24]
