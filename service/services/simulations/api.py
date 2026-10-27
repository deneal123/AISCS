from __future__ import annotations

import asyncio
import json
from typing import Annotated
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from service.composition.state import get_current_container
from service.models.auth_models import AuthProfile
from service.models.db.db_models import UserFile, UserLaunch
from service.models.key_value import ProcessingStatus, ServiceType
from service.services.simulations.models import SimulationArtifact, SimulationRun
from service.services.simulations.runtime import file_service, generator_client
from service.settings import config
from service.shared.security.auth_checker import check_auth
from service.shared.security.origins import websocket_origin_allowed

router = APIRouter(prefix="/api/simulations/v1", tags=["Simulations"])
Owner = Annotated[AuthProfile, Depends(check_auth)]


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    title: str = Field(default="Локальная модель", min_length=1, max_length=120)
    configuration: dict
    parent_run_id: UUID | None = None


def view(run: SimulationRun, *, include_result: bool = True) -> dict:
    return {
        "id": str(run.id),
        "job_id": str(run.job_id),
        "title": run.title,
        "state": run.state,
        "configuration": run.configuration,
        "configuration_sha256": run.configuration_sha256,
        "attempt_id": str(run.attempt_id) if run.attempt_id else None,
        "parent_run_id": str(run.parent_run_id) if run.parent_run_id else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat(timespec="microseconds") if run.updated_at else None,
        "result": run.result if include_result else None,
        "error": run.error,
    }


async def owned(session, run_id: UUID, user_id: UUID, lock=False) -> SimulationRun:
    query = select(SimulationRun).where(
        SimulationRun.id == run_id, SimulationRun.user_id == user_id
    )
    if lock:
        query = query.with_for_update()
    run = (await session.execute(query)).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "Опыт не найден")
    return run


@router.get("/catalog")
async def catalog(owner: Owner):
    try:
        async with generator_client() as client:
            response = await client.get("/capabilities")
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(503, "Вычислительный сервис недоступен") from exc


@router.post("/runs", status_code=201)
async def create_run(payload: RunCreate, owner: Owner):
    if len(json.dumps(payload.configuration)) > 20000:
        raise HTTPException(422, "Слишком большая конфигурация")
    try:
        async with generator_client() as client:
            response = await client.post("/v1/validate", json=payload.configuration)
        if response.status_code == 422:
            raise HTTPException(422, "Недопустимые параметры модели")
        response.raise_for_status()
        checked = response.json()
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(503, "Не удалось проверить конфигурацию") from exc
    infra = get_current_container().infra
    async with infra.pg_connector.get_session_context() as session:
        prior = (
            await session.execute(
                select(SimulationRun).where(
                    SimulationRun.user_id == owner.user_id,
                    SimulationRun.request_id == payload.request_id,
                )
            )
        ).scalar_one_or_none()
        if prior:
            if (
                prior.configuration_sha256 != checked["configuration_sha256"]
                or prior.parent_run_id != payload.parent_run_id
                or prior.title != payload.title
            ):
                raise HTTPException(409, "Ключ запроса уже использован для другого опыта")
            return view(prior)
        if payload.parent_run_id:
            await owned(session, payload.parent_run_id, owner.user_id)
        job_id, run_id = uuid4(), uuid4()
        session.add(
            UserLaunch(
                id=job_id,
                user_id=owner.user_id,
                type=ServiceType.SIMULATION,
                status=ProcessingStatus.NEW,
                payload={"run_id": str(run_id)},
            )
        )
        await session.flush()
        run = SimulationRun(
            id=run_id,
            job_id=job_id,
            user_id=owner.user_id,
            request_id=payload.request_id,
            parent_run_id=payload.parent_run_id,
            title=payload.title,
            state="queued",
            configuration=checked["configuration"],
            configuration_sha256=checked["configuration_sha256"],
        )
        session.add(run)
        try:
            await session.commit()
            await session.refresh(run)
        except IntegrityError:
            await session.rollback()
            prior = (
                await session.execute(
                    select(SimulationRun).where(
                        SimulationRun.user_id == owner.user_id,
                        SimulationRun.request_id == payload.request_id,
                    )
                )
            ).scalar_one()
            if (
                prior.configuration_sha256 != checked["configuration_sha256"]
                or prior.parent_run_id != payload.parent_run_id
                or prior.title != payload.title
            ):
                raise HTTPException(409, "Ключ запроса уже использован") from None
            return view(prior)
        result = view(run)
    # Durable queued row is the outbox. Beat republishes if sending loses its acknowledgement.
    try:
        from service.services.simulations.tasks import emit, execute_run

        async with asyncio.timeout(1):
            await emit(infra, run_id, "queued")
    except Exception:
        pass  # Redis events are disposable; the durable queue intent is retained.
    try:
        await asyncio.to_thread(execute_run.apply_async, args=[str(run_id)], queue="simulation")
    except Exception:
        pass  # queued row is retained; recovery does not require a browser retry.
    return result


@router.get("/runs")
async def list_runs(owner: Owner, limit: int = 30, offset: int = 0):
    limit, offset = max(1, min(limit, 100)), max(0, offset)
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        rows = (
            (
                await session.execute(
                    select(SimulationRun)
                    .options(defer(SimulationRun.result))
                    .where(SimulationRun.user_id == owner.user_id)
                    .order_by(SimulationRun.created_at.desc())
                    .offset(offset)
                    .limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        return {
            "items": [view(row, include_result=False) for row in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None,
        }


@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, owner: Owner):
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        return view(await owned(session, run_id, owner.user_id))


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: UUID, owner: Owner):
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        run = await owned(session, run_id, owner.user_id, lock=True)
        if run.state == "queued":
            run.state = "cancelled"
            job = await session.get(UserLaunch, run.job_id)
            job.status = ProcessingStatus.FAILURE
        elif run.state in {"preparing", "running", "publishing"}:
            run.state = "cancelling"
        await session.commit()
        await session.refresh(run)
        result = view(run)
    try:
        from service.services.simulations.tasks import emit

        async with asyncio.timeout(1):
            await emit(get_current_container().infra, run_id, result["state"])
    except Exception:
        pass
    return result


@router.get("/runs/{run_id}/artifacts")
async def artifacts(run_id: UUID, owner: Owner):
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        await owned(session, run_id, owner.user_id)
        rows = (
            (
                await session.execute(
                    select(SimulationArtifact).where(SimulationArtifact.run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
        return {
            "items": [
                {
                    "id": str(row.id),
                    "file_id": str(row.file_id),
                    "name": row.name,
                    "sha256": row.sha256,
                    "bytes": row.size,
                }
                for row in rows
            ]
        }


@router.get("/runs/{run_id}/manifest")
async def download_manifest(run_id: UUID, owner: Owner):
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        run = await owned(session, run_id, owner.user_id)
        if run.state != "completed" or not run.result:
            raise HTTPException(409, "Результат ещё не сохранён")
        body = json.dumps(run.result["manifest"], ensure_ascii=False, indent=2) + "\n"
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="manifest.json"'},
    )


@router.get("/runs/{run_id}/artifacts/{artifact_id}")
async def download(run_id: UUID, artifact_id: UUID, owner: Owner):
    infra = get_current_container().infra
    async with infra.pg_connector.get_session_context() as session:
        await owned(session, run_id, owner.user_id)
        row = (
            await session.execute(
                select(SimulationArtifact, UserFile)
                .join(UserFile, UserFile.id == SimulationArtifact.file_id)
                .where(
                    SimulationArtifact.id == artifact_id,
                    SimulationArtifact.run_id == run_id,
                    UserFile.user_id == owner.user_id,
                )
            )
        ).first()
        if row is None:
            raise HTTPException(404, "Файл не найден")
        artifact, file = row
        key, name = file.file_name, artifact.name
    data = await file_service(infra).get_file_by_key(file_key=key)
    if data is None:
        raise HTTPException(503, "Файл временно недоступен")
    import hashlib

    if len(data) != artifact.size or hashlib.sha256(data).hexdigest() != artifact.sha256:
        raise HTTPException(503, "Целостность файла не подтверждена")
    return Response(
        data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.websocket("/runs/{run_id}/events")
async def events(websocket: WebSocket, run_id: UUID):
    if not websocket_origin_allowed(websocket.headers.get("origin"), config):
        await websocket.close(code=1008)
        return
    try:
        owner = check_auth(websocket.cookies.get("auth_token"))
        async with get_current_container().infra.pg_connector.get_session_context() as session:
            await owned(session, run_id, owner.user_id)
    except Exception:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    infra = get_current_container().infra
    cursor = "0-0"
    try:
        while True:
            # Recheck authorization from durable ownership, fail closed if DB is unavailable.
            async with infra.pg_connector.get_session_context() as session:
                run = await owned(session, run_id, owner.user_id)
                snapshot = view(run)
            if infra.redis_client:
                batches = await infra.redis_client.xread(
                    {f"simulation:{run_id}:events": cursor}, count=30, block=500
                )
                for _, entries in batches:
                    for event_id, fields in entries:
                        cursor = event_id.decode() if isinstance(event_id, bytes) else event_id
                        payload = fields.get(b"data", fields.get("data", "{}"))
                        await websocket.send_json({"id": cursor, "event": json.loads(payload)})
            await websocket.send_json({"type": "snapshot", "run": snapshot})
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        await websocket.close(code=1011)
