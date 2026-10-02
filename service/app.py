"""Read-only HTTP transport for the research knowledge base."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .contracts import (
    DATA_SCHEMA_VERSION,
    ERROR_CODES,
    READ_ENDPOINTS,
    SERVICE_NAME,
    SERVICE_VERSION,
)
from .core import DataError, ResearchRepository, default_data_dir
from .integrity import validate_repository

logger = logging.getLogger("research-sidecar")


def _error(code: str, detail: str, status: int) -> JSONResponse:
    assert code in ERROR_CODES, f"undeclared research sidecar error: {code}"
    return JSONResponse({"error": code, "detail": detail}, status_code=status)


def create_app(repository: ResearchRepository | None = None) -> FastAPI:
    repo = repository or ResearchRepository()
    from .knowledge.engine import KnowledgeEngine

    knowledge = KnowledgeEngine(repo)
    application = FastAPI(
        title="Aspa research knowledge-base sidecar",
        version=SERVICE_VERSION,
        docs_url=None,
        redoc_url=None,
    )

    @application.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "query_failed"
        return _error(code, str(exc.detail), exc.status_code)

    @application.exception_handler(RequestValidationError)
    async def request_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error("invalid_request", str(exc.errors())[:600], 422)

    @application.exception_handler(DataError)
    async def data_error(_request: Request, exc: DataError) -> JSONResponse:
        return _error("data_invalid", str(exc), 503)

    @application.get("/health")
    async def health() -> dict:
        metadata = repo.metadata()
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "data_schema_version": DATA_SCHEMA_VERSION,
            "fingerprint": metadata["fingerprint"],
            "contract": {"read_only": True, "endpoints": list(READ_ENDPOINTS)},
        }

    @application.get("/ready")
    async def ready() -> JSONResponse:
        report = validate_repository(repo.data_dir)
        return JSONResponse(report, status_code=200 if report["ok"] else 503)

    @application.get("/v1/meta")
    async def metadata() -> dict:
        return repo.metadata()

    @application.get("/v1/sources")
    async def sources(
        q: str | None = Query(default=None, max_length=300),
        validation_status: str | None = None,
        screening_status: str | None = None,
        evidence_role: str | None = None,
        target_construct: str | None = None,
        risk_flag: str | None = None,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        return repo.list_sources(
            query=q,
            validation_status=validation_status,
            screening_status=screening_status,
            evidence_role=evidence_role,
            target_construct=target_construct,
            risk_flag=risk_flag,
            limit=limit,
            offset=offset,
        )

    @application.get("/v1/sources/{source_id}")
    async def source(source_id: str) -> JSONResponse:
        item = repo.get_source(source_id)
        if item is None:
            return _error("not_found", f"source not found: {source_id}", 404)
        return JSONResponse(item)

    @application.get("/v1/clusters")
    async def clusters(include_retired: bool = False) -> dict:
        items = repo.list_clusters(include_retired=include_retired)
        return {"items": items, "total": len(items)}

    @application.get("/v1/clusters/{cluster_id}")
    async def cluster(cluster_id: str) -> JSONResponse:
        item = repo.get_cluster(cluster_id)
        if item is None:
            return _error("not_found", f"cluster not found: {cluster_id}", 404)
        return JSONResponse(item)

    @application.get("/v1/evidence-summary")
    async def evidence_summary() -> dict:
        return repo.evidence_summary()

    @application.get("/v1/export/sources.jsonl", response_class=PlainTextResponse)
    async def export_sources() -> PlainTextResponse:
        return PlainTextResponse(
            repo.export_jsonl(),
            media_type="application/x-ndjson; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="research-sources.jsonl"'},
        )

    @application.get("/v1/knowledge/status")
    def knowledge_status() -> dict:
        return knowledge.status()

    @application.get("/v1/knowledge/search")
    def search_knowledge(
        q: str = Query(max_length=2000),
        mode: str = "hybrid",
        limit: int = Query(default=10, ge=1, le=100),
        source_id: str | None = None,
        target_construct: str | None = None,
        subject_domain: str | None = None,
        node_type: str | None = None,
        include_unreviewed: bool = False,
    ) -> dict:
        filters = {
            k: v
            for k, v in {
                "source_id": source_id,
                "target_construct": target_construct,
                "subject_domain": subject_domain,
                "type": node_type,
            }.items()
            if v
        }
        return knowledge.search(
            q, filters=filters, mode=mode, limit=limit, include_unreviewed=include_unreviewed
        )

    @application.get("/v1/knowledge/evidence/{node_id}")
    def get_evidence(node_id: str, include_unreviewed: bool = False) -> dict:
        return knowledge.evidence(node_id, include_unreviewed=include_unreviewed)

    @application.get("/v1/knowledge/graph/{node_id}")
    def graph_context(
        node_id: str,
        depth: int = Query(default=1, ge=0, le=2),
        edge_types: Annotated[list[str] | None, Query()] = None,
        include_unreviewed: bool = False,
    ) -> dict:
        return knowledge.graph(
            node_id, depth=depth, edge_types=edge_types, include_unreviewed=include_unreviewed
        )

    return application


app = create_app()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    port = int(os.environ.get("PORT", "8080"))
    data_dir = Path(os.environ.get("RESEARCH_DATA_DIR", default_data_dir()))
    logger.info("research sidecar on :%s | data=%s | contract=%s", port, data_dir, SERVICE_VERSION)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
