from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import tempfile
from typing import Annotated, Literal
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
from service.services.simulations.inputs.current_source import (
    CurrentSourceUnavailable,
    owned_current_source,
)
from service.services.simulations.inputs.fragment_package import build_fragment_package
from service.services.simulations.inputs.fragment_source import (
    FragmentSourceUnavailable,
    owned_fragment_source,
)
from service.services.simulations.inputs.fragment_target_candidates import (
    fragment_target_candidates,
)
from service.services.simulations.inputs.pulse_waveform import validate_projected_waveform
from service.services.simulations.inputs.replay_source import (
    ReplaySourceUnavailable,
    owned_replay_source,
)
from service.services.simulations.inputs.spatial import (
    ContactPositionsRequest,
    ContactScreenRequest,
    NativeFieldRequest,
    SpatialCandidatesRequest,
    StrictFloat,
    valid_contact_screen,
    valid_native_field,
    valid_spatial_candidates,
)
from service.services.simulations.models import SimulationArtifact, SimulationRun
from service.services.simulations.rerecord import RerecordError, transfer_rerecord
from service.services.simulations.runtime import file_service, generator_client, simulation_queue
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


class RerecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    electrode_um: tuple[StrictFloat, StrictFloat, StrictFloat]
    reference_um: tuple[StrictFloat, StrictFloat, StrictFloat]


class FieldProxyFromFragmentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    request_id: UUID
    gain: float
    allow_partial_geometry: bool = Field(strict=True)
    allow_missing_curvature: bool = Field(strict=True)
    allow_contact_exclusion: bool = Field(strict=True)


class FieldProxyFromSimulationRequest(FieldProxyFromFragmentRequest):
    simulation: dict
    graph_manifest_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    seed: int = Field(strict=True, ge=0, le=2**31 - 1)


@router.post("/runs/{run_id}/rerecord-preview")
async def rerecord_preview(run_id: UUID, payload: RerecordRequest, owner: Owner):
    infra = get_current_container().infra
    try:
        async with infra.pg_connector.get_session_context() as session:
            source = await owned_current_source(session, owner.user_id, run_id)
    except CurrentSourceUnavailable as exc:
        raise HTTPException(404, "Архив токов недоступен") from exc
    try:
        async with generator_client() as client:
            return await transfer_rerecord(
                infra.storage, client, source, payload.electrode_um, payload.reference_um
            )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise HTTPException(429, "Расчёт записи занят") from exc
        if exc.response.status_code == 422:
            raise HTTPException(422, "Недопустимое положение контактов или архив") from exc
        raise HTTPException(503, "Пересчёт записи временно недоступен") from exc
    except (httpx.HTTPError, RerecordError, OSError, RuntimeError) as exc:
        raise HTTPException(503, "Пересчёт записи временно недоступен") from exc


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
    return await create_checked_run(payload, owner, checked)


@router.post("/replays", status_code=201)
async def create_replay(payload: RunCreate, owner: Owner):
    if len(json.dumps(payload.configuration)) > 20000:
        raise HTTPException(422, "Слишком большая конфигурация")
    try:
        source_id = UUID(payload.configuration["source_run_id"])
        graph = payload.configuration["graph_manifest_sha256"]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, "Недопустимый источник записи") from exc
    if payload.parent_run_id is not None and payload.parent_run_id != source_id:
        raise HTTPException(422, "Источник и родительский опыт должны совпадать")
    infra = get_current_container().infra
    try:
        async with infra.pg_connector.get_session_context() as session:
            source = await owned_replay_source(session, owner.user_id, source_id, graph)
    except ReplaySourceUnavailable as exc:
        raise HTTPException(404, "Исходная запись недоступна") from exc
    try:
        async with generator_client() as client:
            response = await client.post("/v1/replay-validate", json=payload.configuration)
        if response.status_code in {404, 409, 422}:
            raise HTTPException(422, "Недопустимые параметры воспроизведения")
        response.raise_for_status()
        checked = response.json()
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(503, "Не удалось проверить конфигурацию") from exc
    try:
        normalized = checked["configuration"]
        requested = {**payload.configuration, "source_run_id": str(source_id)}
        digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"),
                                           allow_nan=False).encode("utf-8")).hexdigest()
        if (not isinstance(normalized, dict) or normalized.get("source_run_id") != str(source_id)
                or normalized.get("graph_manifest_sha256") != graph
                or normalized != requested
                or checked["configuration_sha256"] != digest):
            raise ValueError("replay_validation_mismatch")
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, "Ответ вычислительного сервиса не прошёл проверку") from exc
    try:
        source_duration = source.description["duration_ms"]
        replay_duration = normalized["simulation"]["duration_ms"]
        if (type(source_duration) not in (int, float) or not math.isfinite(source_duration)
                or source_duration <= 0 or type(replay_duration) not in (int, float)
                or not math.isfinite(replay_duration) or replay_duration <= 0):
            raise ValueError("invalid_duration")
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, "Длительность исходной записи недоступна") from exc
    if replay_duration > source_duration:
        raise HTTPException(422, "Длительность превышает исходную запись")
    return await create_checked_run(payload.model_copy(update={"parent_run_id": source_id}),
                                    owner, checked)


@router.post("/field-graph-runs", status_code=201)
async def create_field_graph_run(payload: RunCreate, owner: Owner):
    if payload.parent_run_id is not None or len(json.dumps(payload.configuration)) > 20000:
        raise HTTPException(422, "Invalid field-graph configuration")
    try:
        async with generator_client() as client:
            response = await client.post("/v1/field-graph-validate", json=payload.configuration)
        if response.status_code in {404, 409, 422}:
            raise HTTPException(422, "Invalid field-graph configuration")
        response.raise_for_status()
        checked = response.json()
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(503, "Field-graph validation unavailable") from exc

    def without_none(value):
        if isinstance(value, dict):
            return {key: without_none(item) for key, item in value.items() if item is not None}
        if isinstance(value, list):
            return [without_none(item) for item in value]
        return value

    try:
        normalized = checked["configuration"]
        digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"),
                                           allow_nan=False).encode("utf-8")).hexdigest()
        if (not isinstance(normalized, dict) or normalized != without_none(payload.configuration)
                or checked["configuration_sha256"] != digest):
            raise ValueError("field_graph_validation_mismatch")
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, "Invalid field-graph validation response") from exc
    return await create_checked_run(payload, owner, checked)


@router.post('/field-proxy-runs', status_code=201)
async def create_field_proxy_run(payload: RunCreate, owner: Owner):
    """Queue an explicitly experimental whole-graph model, not a physical recording."""
    if payload.parent_run_id is None or len(json.dumps(payload.configuration)) > 20000:
        raise HTTPException(422, 'Invalid field-proxy configuration')
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        scene = await owned(session, payload.parent_run_id, owner.user_id)
        result = scene.result if isinstance(scene.result, dict) else {}
        preview = result.get('preview') if isinstance(result.get('preview'), dict) else {}
        graph = preview.get('connectome') if isinstance(preview.get('connectome'), dict) else {}
        if (scene.state != 'completed' or graph.get('manifest_sha256')
                != payload.configuration.get('graph_manifest_sha256')):
            raise HTTPException(409, 'Версия графа не соответствует сцене')
    try:
        async with generator_client() as client:
            response = await client.post('/v1/field-proxy-validate', json=payload.configuration)
        if response.status_code in {404, 409, 422}:
            raise HTTPException(422, 'Invalid field-proxy configuration')
        response.raise_for_status()
        checked = response.json()
        normalized = checked['configuration']
        digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(',', ':'),
                                           allow_nan=False).encode('utf8')).hexdigest()
        if (not isinstance(normalized, dict) or normalized != payload.configuration
                or checked['configuration_sha256'] != digest):
            raise ValueError('field_proxy_validation_mismatch')
    except (httpx.HTTPError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, 'Field-proxy validation unavailable') from exc
    return await create_checked_run(payload, owner, checked)


@router.post('/runs/{run_id}/field-proxy-direct', status_code=201)
async def create_field_proxy_direct(
    run_id: UUID, payload: FieldProxyFromSimulationRequest, owner: Owner
):
    """Derive a network-only stimulus from the owner's compatible scene."""
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        scene = await owned(session, run_id, owner.user_id)
        result = scene.result if isinstance(scene.result, dict) else {}
        preview = result.get('preview') if isinstance(result.get('preview'), dict) else {}
        graph = preview.get('connectome') if isinstance(preview.get('connectome'), dict) else {}
        if (scene.state != 'completed'
                or graph.get('manifest_sha256') != payload.graph_manifest_sha256):
            raise HTTPException(409, 'Версия графа не соответствует сцене')
    try:
        data = payload.model_dump(mode='json', exclude={'request_id'})
        async with generator_client() as client:
            response = await client.post('/v1/field-proxy-from-simulation', json=data)
        if response.status_code in {404, 409, 422}:
            raise HTTPException(422, 'Невозможно согласовать стимул с моделью сети')
        response.raise_for_status()
        checked = response.json()
        derived = checked['configuration']
        digest = hashlib.sha256(json.dumps(derived, sort_keys=True, separators=(',', ':'),
                                           allow_nan=False).encode('utf8')).hexdigest()
        keys = ('source_um', 'return_um', 'current_na', 'conductivity_s_m', 'clearance_um',
                'coordinate_frame')
        if (not isinstance(derived, dict) or checked['configuration_sha256'] != digest
                or derived.get('graph_manifest_sha256') != payload.graph_manifest_sha256
                or derived.get('seed') != payload.seed or derived.get('gain') != payload.gain
                or any(derived.get(key) != payload.simulation.get(key) for key in keys)
                or any(derived.get(key) != getattr(payload, key) for key in (
                    'allow_partial_geometry', 'allow_missing_curvature', 'allow_contact_exclusion'))
                or not isinstance(derived.get('waveform'), list)
                or len(derived['waveform']) != payload.simulation.get('duration_ms')):
            raise ValueError('field_proxy_source_mismatch')
        validate_projected_waveform(payload.simulation, derived['waveform'])
    except (httpx.HTTPError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, 'Не удалось проверить параметры модели сети') from exc
    request = RunCreate(request_id=payload.request_id, parent_run_id=run_id,
                        title='Быстрая модель ЦНС', configuration=derived)
    return await create_checked_run(request, owner, checked)


@router.post('/fragment-population-runs', status_code=201)
async def create_fragment_population_run(payload: RunCreate, owner: Owner):
    if len(json.dumps(payload.configuration)) > 20000:
        raise HTTPException(422, 'Invalid fragment population configuration')
    if payload.parent_run_id is not None:
        try:
            async with get_current_container().infra.pg_connector.get_session_context() as session:
                await owned_replay_source(session, owner.user_id, payload.parent_run_id,
                                          payload.configuration.get('graph_manifest_sha256'))
        except ReplaySourceUnavailable as exc:
            raise HTTPException(
                404, 'Исходная сцена недоступна или не соответствует графу'
            ) from exc
    try:
        async with generator_client() as client:
            response = await client.post(
                '/v1/fragment-population-validate', json=payload.configuration
            )
        if response.status_code in {404, 409, 422}:
            raise HTTPException(422, 'Invalid fragment population configuration')
        response.raise_for_status()
        checked = response.json()
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(503, 'Fragment population validation unavailable') from exc

    def without_none(value):
        if isinstance(value, dict):
            return {key: without_none(item) for key, item in value.items() if item is not None}
        if isinstance(value, list):
            return [without_none(item) for item in value]
        return value

    try:
        normalized = checked['configuration']
        digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(',', ':'),
                                           allow_nan=False).encode('utf8')).hexdigest()
        if (not isinstance(normalized, dict) or normalized != without_none(payload.configuration)
                or checked['configuration_sha256'] != digest):
            raise ValueError('fragment_configuration_mismatch')
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, 'Invalid fragment validation response') from exc
    return await create_checked_run(payload, owner, checked)


@router.post('/runs/{run_id}/field-proxy', status_code=201)
async def create_field_proxy_from_fragment(
    run_id: UUID, payload: FieldProxyFromFragmentRequest, owner: Owner
):
    """Derive a coarse-network stimulus from the owner's completed physical run."""
    try:
        async with get_current_container().infra.pg_connector.get_session_context() as session:
            run = await owned(session, run_id, owner.user_id)
            graph = run.configuration.get('graph_manifest_sha256') if isinstance(
                run.configuration, dict) else None
            source = await owned_fragment_source(session, owner.user_id, run_id, graph)
    except FragmentSourceUnavailable as exc:
        raise HTTPException(404, 'Исходный расчёт недоступен') from exc
    try:
        async with generator_client() as client:
            response = await client.post('/v1/field-proxy-from-fragment', json={
                'population': source.configuration, 'gain': payload.gain,
                'allow_partial_geometry': payload.allow_partial_geometry,
                'allow_missing_curvature': payload.allow_missing_curvature,
                'allow_contact_exclusion': payload.allow_contact_exclusion,
            })
        if response.status_code in {404, 409, 422}:
            raise HTTPException(422, 'Невозможно согласовать стимул с моделью сети')
        response.raise_for_status()
        checked = response.json()
        derived = checked['configuration']
        simulation = source.configuration['simulation']
        keys = ('source_um', 'return_um', 'current_na', 'conductivity_s_m', 'clearance_um',
                'coordinate_frame')
        digest = hashlib.sha256(json.dumps(derived, sort_keys=True, separators=(',', ':'),
                                           allow_nan=False).encode('utf8')).hexdigest()
        if (not isinstance(derived, dict) or checked['configuration_sha256'] != digest
                or derived.get('graph_manifest_sha256') != graph
                or derived.get('seed') != source.configuration['seed']
                or derived.get('gain') != payload.gain
                or any(derived.get(key) != simulation.get(key) for key in keys)
                or any(derived.get(key) != getattr(payload, key) for key in (
                    'allow_partial_geometry', 'allow_missing_curvature', 'allow_contact_exclusion'))
                or not isinstance(derived.get('waveform'), list)
                or len(derived['waveform']) != simulation['duration_ms']):
            raise ValueError('field_proxy_source_mismatch')
        validate_projected_waveform(simulation, derived['waveform'])
    except (httpx.HTTPError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, 'Не удалось проверить параметры модели сети') from exc
    request = RunCreate(request_id=payload.request_id, parent_run_id=run_id,
                        title='Модельный ответ ЦНС', configuration=derived)
    return await create_checked_run(request, owner, checked)


@router.post('/runs/{run_id}/population-feedback-source')
@router.post('/runs/{run_id}/population-target-source')
async def prepare_population_target_source(run_id: UUID, owner: Owner):
    infra = get_current_container().infra
    try:
        async with infra.pg_connector.get_session_context() as session:
            run = await owned(session, run_id, owner.user_id)
            graph = run.configuration.get('graph_manifest_sha256') if isinstance(
                run.configuration, dict) else None
            source = await owned_fragment_source(session, owner.user_id, run_id, graph)
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b') as package:
            receipt = await build_fragment_package(infra.storage, source.manifest, source.files,
                                                   package)
    except (FragmentSourceUnavailable, ValueError) as exc:
        raise HTTPException(422, 'Исходный расчёт недоступен или повреждён') from exc
    return {**receipt, 'graph_manifest_sha256': graph,
            'duration_ms': source.configuration.get('simulation', {}).get('duration_ms'),
            'source_ids': source.configuration.get('source_ids')}


@router.get('/runs/{run_id}/population-target-candidates/{target_id}')
async def list_population_target_candidates(run_id: UUID, target_id: int, owner: Owner):
    infra = get_current_container().infra
    try:
        async with infra.pg_connector.get_session_context() as session:
            run = await owned(session, run_id, owner.user_id)
            graph = run.configuration.get('graph_manifest_sha256') if isinstance(
                run.configuration, dict) else None
            source = await owned_fragment_source(session, owner.user_id, run_id, graph)
        return await fragment_target_candidates(infra.storage, source, target_id)
    except (FragmentSourceUnavailable, ValueError, OSError) as exc:
        raise HTTPException(422, 'Не удалось проверить события исходного расчёта') from exc


@router.get('/runs/{run_id}/population-target-runs/{target_id}')
async def list_population_target_runs(run_id: UUID, target_id: int, owner: Owner):
    if not 0 < target_id < 2**63:
        raise HTTPException(422, 'Недопустимый идентификатор нейрона')
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        await owned(session, run_id, owner.user_id)
        rows = (await session.execute(
            select(SimulationRun).options(defer(SimulationRun.result))
            .where(SimulationRun.user_id == owner.user_id, SimulationRun.parent_run_id == run_id,
                   SimulationRun.configuration.has_key('source_package_sha256'),
                   SimulationRun.configuration['target_id'].as_string() == str(target_id))
            .order_by(SimulationRun.created_at.desc()).limit(30)
        )).scalars().all()
        return {'items': [view(row, include_result=False) for row in rows]}


@router.get('/runs/{run_id}/population-feedback-runs')
async def list_population_feedback_runs(run_id: UUID, owner: Owner):
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        await owned(session, run_id, owner.user_id)
        rows = (await session.execute(
            select(SimulationRun).options(defer(SimulationRun.result))
            .where(SimulationRun.user_id == owner.user_id, SimulationRun.parent_run_id == run_id,
                   SimulationRun.configuration.has_key('source_package_sha256'),
                   SimulationRun.configuration.has_key('excitatory'),
                   SimulationRun.configuration.has_key('inhibitory'))
            .order_by(SimulationRun.created_at.desc()).limit(30)
        )).scalars().all()
        return {'items': [view(row, include_result=False) for row in rows]}


@router.get('/runs/{run_id}/field-proxy-runs')
async def list_field_proxy_runs(run_id: UUID, owner: Owner, limit: int = 10):
    limit = max(1, min(limit, 100))
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        await owned(session, run_id, owner.user_id)
        rows = (await session.execute(
            select(SimulationRun).options(defer(SimulationRun.result)).where(
                SimulationRun.user_id == owner.user_id, SimulationRun.parent_run_id == run_id,
                SimulationRun.configuration.has_key('waveform'),
                SimulationRun.configuration.has_key('gain'),
                SimulationRun.configuration['coordinate_frame'].astext == 'male-cns-v1.0-native-um',
            ).order_by(SimulationRun.created_at.desc()).limit(limit)
        )).scalars().all()
        return {'items': [view(row, include_result=False) for row in rows]}


@router.post('/population-feedback-runs', status_code=201)
async def create_population_feedback_run(payload: RunCreate, owner: Owner):
    if payload.parent_run_id is None or len(json.dumps(payload.configuration)) > 50000:
        raise HTTPException(422, 'A source run and valid parameters are required')
    infra = get_current_container().infra
    try:
        async with infra.pg_connector.get_session_context() as session:
            source = await owned_fragment_source(session, owner.user_id, payload.parent_run_id,
                payload.configuration.get('graph_manifest_sha256'))
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b') as package:
            receipt = await build_fragment_package(infra.storage, source.manifest, source.files,
                                                   package)
        if (payload.configuration.get('source_package_sha256') != receipt['sha256']
                or payload.configuration.get('source_manifest_sha256')
                   != receipt['manifest_sha256']):
            raise ValueError('feedback_source_changed')
    except (FragmentSourceUnavailable, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, 'Source run is unavailable or has changed') from exc
    try:
        async with generator_client() as client:
            response = await client.post('/v1/population-feedback-validate',
                                         json=payload.configuration)
        if response.status_code in {404, 409, 422}:
            raise HTTPException(422, 'Invalid feedback configuration')
        response.raise_for_status()
        checked = response.json()
        normalized = checked['configuration']
        digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(',', ':'),
                                           allow_nan=False).encode('utf8')).hexdigest()
        if normalized != payload.configuration or checked['configuration_sha256'] != digest:
            raise ValueError('feedback_configuration_mismatch')
    except (httpx.HTTPError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, 'Feedback configuration validation is unavailable') from exc
    return await create_checked_run(payload, owner, checked)


@router.post('/population-target-runs', status_code=201)
async def create_population_target_run(payload: RunCreate, owner: Owner):
    if payload.parent_run_id is None or len(json.dumps(payload.configuration)) > 50000:
        raise HTTPException(422, 'Требуется исходный расчёт и корректные параметры')
    infra = get_current_container().infra
    try:
        async with infra.pg_connector.get_session_context() as session:
            source = await owned_fragment_source(session, owner.user_id, payload.parent_run_id,
                                                payload.configuration.get('graph_manifest_sha256'))
        source_ids = source.configuration['source_ids']
        selected = payload.configuration['source_ids']
        if (not isinstance(source_ids, list) or not isinstance(selected, list)
                or not selected or any(type(body) is not int or body not in source_ids
                                       for body in selected)
                or payload.configuration['target_id'] in source_ids
                or payload.configuration['duration_ms']
                   != source.configuration['simulation']['duration_ms']):
            raise ValueError('target_source_mismatch')
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b') as package:
            receipt = await build_fragment_package(infra.storage, source.manifest, source.files,
                                                   package)
        if (payload.configuration.get('source_package_sha256') != receipt['sha256']
                or payload.configuration.get('source_manifest_sha256')
                   != receipt['manifest_sha256']):
            raise ValueError('target_source_changed')
    except (FragmentSourceUnavailable, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, 'Исходный расчёт или параметры повтора недоступны') from exc
    try:
        async with generator_client() as client:
            response = await client.post('/v1/population-target-validate',
                                         json=payload.configuration)
        if response.status_code in {404, 409, 422}:
            raise HTTPException(422, 'Недопустимые параметры повтора')
        response.raise_for_status()
        checked = response.json()
        normalized = checked['configuration']
        digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(',', ':'),
                                           allow_nan=False).encode('utf8')).hexdigest()
        if normalized != payload.configuration or checked['configuration_sha256'] != digest:
            raise ValueError('target_configuration_mismatch')
    except (httpx.HTTPError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, 'Не удалось проверить параметры повтора') from exc
    return await create_checked_run(payload, owner, checked)


async def create_checked_run(payload: RunCreate, owner: AuthProfile, checked: dict):
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
            execution_queue=simulation_queue(),
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
        await asyncio.to_thread(
            execute_run.apply_async, args=[str(run_id)], queue=simulation_queue()
        )
    except Exception:
        pass  # queued row is retained; recovery does not require a browser retry.
    return result


@router.get("/runs")
async def list_runs(owner: Owner, limit: int = 30, offset: int = 0, include_replays: bool = False):
    limit, offset = max(1, min(limit, 100)), max(0, offset)
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        query = (select(SimulationRun).options(defer(SimulationRun.result))
                 .where(SimulationRun.user_id == owner.user_id,
                        SimulationRun.hidden_from_history.is_(False)))
        if not include_replays:
            # Replay inputs have a different configuration and cannot be loaded
            # into the existing simulation editor as an ordinary model preset.
            query = query.where(~SimulationRun.configuration.has_key("source_run_id"),
                                ~SimulationRun.configuration.has_key("source_cells"),
                                ~SimulationRun.configuration.has_key("source_ids"))
        rows = (
            (
                await session.execute(
                    query.order_by(SimulationRun.created_at.desc())
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


@router.get("/field-graph-runs")
async def list_field_graph_runs(owner: Owner, limit: int = 30, offset: int = 0):
    limit, offset = max(1, min(limit, 100)), max(0, offset)
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        rows = (await session.execute(
            select(SimulationRun).options(defer(SimulationRun.result))
            .where(SimulationRun.user_id == owner.user_id,
                   SimulationRun.configuration.has_key("source_cells"),
                   SimulationRun.configuration.has_key("replay_ids"))
            .order_by(SimulationRun.created_at.desc()).offset(offset).limit(limit + 1)
        )).scalars().all()
        return {"items": [view(row, include_result=False) for row in rows[:limit]],
                "next_offset": offset + limit if len(rows) > limit else None}


@router.get("/scene-template")
async def scene_template(owner: Owner):
    """Find an owned CNS scene, including one removed from the history list."""
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        query = (select(SimulationRun).where(
            SimulationRun.user_id == owner.user_id,
            SimulationRun.state == "completed",
            SimulationRun.configuration["model_id"].astext == "male-cns-hybrid-v1",
            SimulationRun.result["preview"]["connectome"]["manifest_sha256"].astext.is_not(None),
        ).order_by(SimulationRun.created_at.desc()).limit(1))
        scene = (await session.execute(query)).scalar_one_or_none()
        if scene is None:
            raise HTTPException(404, "Подготовленная сцена ЦНС не найдена")
        return view(scene)


@router.get('/fragment-population-runs')
async def list_fragment_population_runs(owner: Owner, limit: int = 30, offset: int = 0,
                                        parent_run_id: UUID | None = None):
    limit, offset = max(1, min(limit, 100)), max(0, offset)
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        query = (select(SimulationRun).options(defer(SimulationRun.result))
            .where(SimulationRun.user_id == owner.user_id,
                   SimulationRun.configuration.has_key('source_ids'),
                   SimulationRun.configuration.has_key('max_distance_um')))
        if parent_run_id is not None:
            await owned(session, parent_run_id, owner.user_id)
            query = query.where(SimulationRun.parent_run_id == parent_run_id)
        rows = (await session.execute(query.order_by(SimulationRun.created_at.desc())
                                     .offset(offset).limit(limit + 1))).scalars().all()
        return {'items': [view(row, include_result=False) for row in rows[:limit]],
                'next_offset': offset + limit if len(rows) > limit else None}


@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, owner: Owner):
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        return view(await owned(session, run_id, owner.user_id))


@router.delete("/runs/{run_id}", status_code=204)
async def remove_run_from_history(run_id: UUID, owner: Owner):
    """Remove a finished run from history while preserving dependent results."""
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        run = await owned(session, run_id, owner.user_id, lock=True)
        if run.state not in {"completed", "failed", "cancelled"}:
            raise HTTPException(409, "Сначала остановите расчёт")
        run.hidden_from_history = True
        await session.commit()
    return Response(status_code=204)


@router.get("/runs/{run_id}/replays")
async def list_replays(run_id: UUID, owner: Owner, limit: int = 30, offset: int = 0):
    limit, offset = max(1, min(limit, 100)), max(0, offset)
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        await owned(session, run_id, owner.user_id)
        rows = (await session.execute(
            select(SimulationRun).options(defer(SimulationRun.result))
            .where(SimulationRun.user_id == owner.user_id, SimulationRun.parent_run_id == run_id,
                   SimulationRun.configuration.has_key("source_run_id"))
            .order_by(SimulationRun.created_at.desc()).offset(offset).limit(limit + 1)
        )).scalars().all()
        return {"items": [view(row, include_result=False) for row in rows[:limit]],
                "next_offset": offset + limit if len(rows) > limit else None}


@router.get("/runs/{run_id}/neurons/{body_id}/outgoing")
async def neuron_outgoing(
    run_id: UUID, body_id: str, owner: Owner, offset: int = 0, limit: int = 20
):
    return await neuron_connections(run_id, body_id, owner, offset, limit, "outgoing")


@router.get("/runs/{run_id}/neurons/{body_id}/incoming")
async def neuron_incoming(
    run_id: UUID, body_id: str, owner: Owner, offset: int = 0, limit: int = 20
):
    return await neuron_connections(run_id, body_id, owner, offset, limit, "incoming")


@router.get("/runs/{run_id}/neurons/{body_id}/morphology")
async def neuron_morphology(run_id: UUID, body_id: str, owner: Owner):
    if (not body_id.isascii() or not body_id.isdigit() or body_id.startswith("0")
            or len(body_id) > 19 or int(body_id) > 2**63 - 1):
        raise HTTPException(422, "Недопустимый идентификатор нейрона")
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        run = await owned(session, run_id, owner.user_id)
        graph = (run.result or {}).get("preview", {}).get("connectome", {})
        if run.state != "completed" or not graph:
            raise HTTPException(409, "В записи нет полного графа")
        expected = graph.get("manifest_sha256")
    try:
        async with generator_client() as client:
            response = await client.get(f"/v1/connectome/morphology/{body_id}")
        if response.status_code == 404:
            raise HTTPException(404, "Морфология нейрона пока недоступна")
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, "Морфология временно недоступна") from exc
    if (not expected or result.get("manifest_sha256") != expected
            or result.get("body_id") != body_id):
        raise HTTPException(409, "Морфология не соответствует записи")
    return result


@router.get("/runs/{run_id}/neurons/{body_id}/{direction}/synapses")
async def neuron_synapses(
    run_id: UUID, body_id: str, direction: Literal["incoming", "outgoing"], owner: Owner,
    offset: int = 0, limit: int = 20,
):
    if (not body_id.isascii() or not body_id.isdigit() or body_id.startswith("0")
            or len(body_id) > 19 or int(body_id) > 2**63 - 1
            or offset < 0 or offset > 25_582_938 or limit < 1 or limit > 20):
        raise HTTPException(422, "Недопустимые параметры запроса синапсов")
    expected = await owned_graph_hash(run_id, owner)
    try:
        async with generator_client() as client:
            response = await client.get(
                f"/v1/connectome/neurons/{body_id}/{direction}/synapses",
                params={"offset": offset, "limit": limit}, timeout=180,
            )
        if response.status_code == 404:
            raise HTTPException(404, "Нейрон не найден")
        if response.status_code == 409:
            raise HTTPException(409, "Синапсы не соответствуют графу")
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, "Синаптические данные временно недоступны") from exc
    if (not isinstance(result, dict) or result.get("graph_manifest_sha256") != expected
            or result.get("body_id") != body_id or result.get("direction") != direction
            or result.get("counts_match") is not True
            or result.get("coordinate_frame") != "male-cns-v1.0-native-8nm"):
        raise HTTPException(409, "Синапсы не соответствуют записи")
    return result


async def owned_graph_hash(run_id: UUID, owner: Owner) -> str:
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        run = await owned(session, run_id, owner.user_id)
        graph = (run.result or {}).get("preview", {}).get("connectome", {})
        expected = graph.get("manifest_sha256")
        if run.state != "completed" or not expected:
            raise HTTPException(409, "В записи нет полного графа")
        return expected


async def owned_spatial_graph(run_id: UUID, owner: Owner) -> tuple[str, int]:
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        run = await owned(session, run_id, owner.user_id)
        graph = (run.result or {}).get("preview", {}).get("connectome", {})
        expected, neurons = graph.get("manifest_sha256"), graph.get("neurons")
        if run.state != "completed" or not expected or type(neurons) is not int or neurons <= 0:
            raise HTTPException(409, "В записи нет полного графа с подтверждённым размером")
        return expected, neurons


async def verified_overview(client, expected: str) -> dict:
    response = await client.get("/v1/connectome/overview")
    response.raise_for_status()
    manifest = response.json()
    if (not isinstance(manifest, dict) or manifest.get("manifest_sha256") != expected
            or not isinstance(manifest.get("chunks"), list)):
        raise HTTPException(409, "Обзор не соответствует записи")
    return manifest


@router.get("/runs/{run_id}/cns-overview")
async def cns_overview(run_id: UUID, owner: Owner):
    expected = await owned_graph_hash(run_id, owner)
    try:
        async with generator_client() as client:
            return await verified_overview(client, expected)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, "Обзор ЦНС временно недоступен") from exc


@router.get("/runs/{run_id}/cns-overview/{name}")
async def cns_overview_chunk(run_id: UUID, name: str, owner: Owner):
    if not re.fullmatch(r"overview-[0-9]{6}\.bin\.gz", name):
        raise HTTPException(422, "Недопустимое имя фрагмента")
    expected = await owned_graph_hash(run_id, owner)
    try:
        async with generator_client() as client:
            manifest = await verified_overview(client, expected)
            record = next((item for item in manifest["chunks"]
                           if isinstance(item, dict) and item.get("file") == name), None)
            if record is None:
                raise HTTPException(404, "Фрагмент обзора не найден")
            response = await client.get(f"/v1/connectome/overview/{name}")
            response.raise_for_status()
            binary = response.content
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, "Обзор ЦНС временно недоступен") from exc
    if (type(record.get("bytes")) is not int or len(binary) != record["bytes"]
            or hashlib.sha256(binary).hexdigest() != record.get("sha256")):
        raise HTTPException(503, "Ошибка целостности фрагмента")
    return Response(binary, media_type="application/gzip")


async def verified_neuropil(client, expected: str) -> dict:
    response = await client.get("/v1/connectome/neuropil")
    response.raise_for_status()
    manifest = response.json()
    if (not isinstance(manifest, dict) or manifest.get("manifest_sha256") != expected
            or not isinstance(manifest.get("meshes"), list)):
        raise HTTPException(409, "Нейропиль не соответствует записи")
    return manifest


@router.get("/runs/{run_id}/neuropil")
async def neuropil(run_id: UUID, owner: Owner):
    expected = await owned_graph_hash(run_id, owner)
    try:
        async with generator_client() as client:
            return await verified_neuropil(client, expected)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, "Области нейропиля временно недоступны") from exc


@router.get("/runs/{run_id}/neuropil/{name}")
async def neuropil_part(run_id: UUID, name: str, owner: Owner):
    pattern = r"(?:fullbrain-roi-v4|malecns-vnc-neuropil-roi-v0)-[1-9]\d*\.bin\.gz"
    if not re.fullmatch(pattern, name):
        raise HTTPException(422, "Недопустимое имя области")
    expected = await owned_graph_hash(run_id, owner)
    try:
        async with generator_client() as client:
            manifest = await verified_neuropil(client, expected)
            record = next((item for item in manifest["meshes"]
                           if isinstance(item, dict) and item.get("file") == name), None)
            if record is None:
                raise HTTPException(404, "Область нейропиля не найдена")
            response = await client.get(f"/v1/connectome/neuropil/{name}")
            response.raise_for_status()
            binary = response.content
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, "Область нейропиля временно недоступна") from exc
    if (type(record.get("bytes")) is not int or len(binary) != record["bytes"]
            or hashlib.sha256(binary).hexdigest() != record.get("sha256")):
        raise HTTPException(503, "Ошибка целостности области нейропиля")
    return Response(binary, media_type="application/gzip")


@router.post("/runs/{run_id}/neurons/{body_id}/native-field")
async def neuron_native_field(
    run_id: UUID, body_id: str, request: NativeFieldRequest, owner: Owner
):
    if (not body_id.isascii() or not body_id.isdigit() or body_id.startswith("0")
            or len(body_id) > 19 or int(body_id) > 2**63 - 1):
        raise HTTPException(422, "Недопустимый идентификатор нейрона")
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        run = await owned(session, run_id, owner.user_id)
        graph = (run.result or {}).get("preview", {}).get("connectome", {})
        if run.state != "completed" or not graph:
            raise HTTPException(409, "В записи нет полного графа")
        expected = graph.get("manifest_sha256")
    try:
        async with generator_client() as client:
            response = await client.post(
                f"/v1/connectome/morphology/{body_id}/field", json=request.model_dump()
            )
        if response.status_code == 404:
            raise HTTPException(404, "Морфология нейрона пока недоступна")
        if response.status_code == 422:
            raise HTTPException(422, "Недопустимые параметры поля")
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, "Расчёт поля временно недоступен") from exc
    if (not isinstance(result, dict) or not expected or result.get("manifest_sha256") != expected
            or result.get("body_id") != body_id
            or result.get("coordinate_frame") != "male-cns-v1.0-native-um"
            or not valid_native_field(result, request)):
        raise HTTPException(409, "Расчёт поля не соответствует записи")
    return result


@router.post("/runs/{run_id}/spatial-candidates")
async def find_spatial_candidates(run_id: UUID, request: SpatialCandidatesRequest, owner: Owner):
    expected, neurons = await owned_spatial_graph(run_id, owner)
    try:
        async with generator_client() as client:
            response = await client.post(
                "/v1/connectome/spatial-candidates", json=request.model_dump(), timeout=None
            )
        if response.status_code == 429:
            raise HTTPException(429, "Другой пространственный поиск ещё выполняется")
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, "Проверенный пространственный индекс пока недоступен") from exc
    if not valid_spatial_candidates(result, request, expected, neurons):
        raise HTTPException(409, "Пространственный поиск не соответствует записи")
    return result


@router.post("/runs/{run_id}/contact-screen")
async def screen_all_contacts(run_id: UUID, request: ContactScreenRequest, owner: Owner):
    return await _screen_contact_request(run_id, request, owner, "/v1/connectome/contact-screen")


@router.post("/runs/{run_id}/contact-positions")
async def screen_contact_positions(run_id: UUID, request: ContactPositionsRequest, owner: Owner):
    return await _screen_contact_request(run_id, request, owner, "/v1/connectome/contact-positions")


async def _screen_contact_request(run_id, request, owner, path):
    expected, neurons = await owned_spatial_graph(run_id, owner)
    try:
        async with generator_client() as client:
            response = await client.post(path, json=request.model_dump(), timeout=None)
        if response.status_code == 429:
            raise HTTPException(429, "Другой пространственный поиск ещё выполняется")
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, "Проверенный индекс контактов пока недоступен") from exc
    if not valid_contact_screen(result, request, expected, neurons):
        raise HTTPException(409, "Проверка контактов не соответствует записи")
    return result


async def neuron_connections(run_id, body_id, owner, offset, limit, direction):
    if (not body_id.isascii() or not body_id.isdigit() or body_id.startswith("0")
            or len(body_id) > 19 or int(body_id) > 2**63 - 1 or not 0 <= offset <= 25_582_938
            or not 1 <= limit <= 100):
        raise HTTPException(422, "Недопустимый запрос к графу")
    async with get_current_container().infra.pg_connector.get_session_context() as session:
        run = await owned(session, run_id, owner.user_id)
        graph = (run.result or {}).get("preview", {}).get("connectome", {})
        if run.state != "completed" or not graph:
            raise HTTPException(409, "В записи нет полного графа")
        expected = graph.get("manifest_sha256")
    try:
        async with generator_client() as client:
            response = await client.get(
                f"/v1/connectome/neurons/{body_id}/{direction}",
                params={"offset": offset, "limit": limit},
            )
        if response.status_code == 404:
            raise HTTPException(404, "Нейрон не найден")
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, "Граф временно недоступен") from exc
    if not expected or result.get("manifest_sha256") != expected:
        raise HTTPException(409, "Версия графа не совпадает с записью")
    return result


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
