"""Stable HTTP and CLI contract for the research sidecar.

Keep this module dependency-free: CI and callers can inspect the contract without
importing FastAPI or loading the corpus.
"""

from __future__ import annotations

SERVICE_NAME = "research"
SERVICE_VERSION = "1.3.0"
DATA_SCHEMA_VERSION = "2.0.0"

ERROR_CODES = frozenset(
    {
        "invalid_request",
        "data_invalid",
        "not_found",
        "query_failed",
    }
)

READ_ENDPOINTS = (
    "GET /health",
    "GET /ready",
    "GET /v1/meta",
    "GET /v1/sources",
    "GET /v1/sources/{source_id}",
    "GET /v1/clusters",
    "GET /v1/clusters/{cluster_id}",
    "GET /v1/evidence-summary",
    "GET /v1/export/sources.jsonl",
)

SOURCE_LIST_FIELDS = frozenset({"items", "total", "limit", "offset"})
ERROR_FIELDS = frozenset({"error", "detail"})
