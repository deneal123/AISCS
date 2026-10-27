"""Private, authenticated executor HTTP contract; ownership remains in the platform backend."""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from service import __version__
from service.contracts import ExecutionRequest, SimulationConfig
from service.domain.catalog import catalog
from service.domain.geometry import local_geometry
from service.domain.placement import validate_contacts
from service.infrastructure.execution.process import Executions


class Ack(BaseModel):
    configuration_sha256: str


def build_app(manager: Executions, secret: str, readiness, catalog_factory=catalog) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        yield
        manager.close()

    app = FastAPI(title="Neural generator executor", version=__version__, lifespan=lifespan)

    def authorize(authorization: str = Header(default="")):
        if not hmac.compare_digest(authorization, "Bearer " + secret):
            raise HTTPException(401, "Invalid service credential")

    def read(execution_id: UUID):
        try:
            return manager.status(str(execution_id))
        except KeyError as exc:
            raise HTTPException(404, "Execution not found") from exc

    protected = [Depends(authorize)]

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/ready", dependencies=protected)
    def ready():
        return readiness()

    @app.get("/capabilities", dependencies=protected)
    def capabilities():
        return catalog_factory()

    @app.post("/v1/validate", dependencies=protected)
    def validate(config: SimulationConfig):
        import numpy as np

        geometry = local_geometry()
        if config.model_id == "male-cns-hybrid-v1":
            from service.settings import connectome_directory

            if not (connectome_directory() / "manifest.json").is_file():
                raise HTTPException(503, "Registered MaleCNS data are not installed")
        try:
            validate_contacts(
                config,
                np.array(geometry["starts_um"]),
                np.array(geometry["ends_um"]),
                np.array(geometry["diameters_um"]),
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"configuration": config.model_dump(), "configuration_sha256": config.digest()}

    @app.post("/v1/executions", dependencies=protected)
    def start(request: ExecutionRequest):
        try:
            UUID(request.execution_id)
            return manager.start(request)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/v1/executions/{execution_id}", dependencies=protected)
    def status(execution_id: UUID):
        return read(execution_id)

    @app.post("/v1/executions/{execution_id}/cancel", dependencies=protected)
    def cancel(execution_id: UUID):
        read(execution_id)
        return manager.cancel(str(execution_id))

    @app.get("/v1/executions/{execution_id}/manifest", dependencies=protected)
    def manifest(execution_id: UUID):
        record = read(execution_id)
        if record["status"] != "completed":
            raise HTTPException(409, "Execution not completed")
        return record["manifest"]

    @app.get("/v1/executions/{execution_id}/artifacts/{name}", dependencies=protected)
    def artifact(execution_id: UUID, name: str):
        record = read(execution_id)
        if record["status"] != "completed" or record["acknowledged"]:
            raise HTTPException(409, "Artifacts unavailable")
        allowed = {item["name"] for item in record["manifest"]["files"]} | {"manifest.json"}
        if name not in allowed or Path(name).name != name:
            raise HTTPException(404, "Artifact not found")
        return FileResponse(
            manager.receipt(str(execution_id)).parent / "output" / name, filename=name
        )

    @app.post("/v1/executions/{execution_id}/ack", dependencies=protected)
    def ack(execution_id: UUID, payload: Ack):
        read(execution_id)
        try:
            return manager.acknowledge(str(execution_id), payload.configuration_sha256)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/v1/executions/{execution_id}/discard", dependencies=protected)
    def discard(execution_id: UUID, payload: Ack):
        read(execution_id)
        try:
            return manager.discard(str(execution_id), payload.configuration_sha256)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    return app
