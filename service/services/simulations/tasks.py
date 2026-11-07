"""Durable queue orchestration; solver files are acknowledged only after verified publication."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy import or_, select

from service.composition.infra import build_infra
from service.infrastructure.messaging.celery_app import celery_app
from service.models.db.db_models import UserLaunch
from service.models.key_value import ProcessingStatus, ServiceType
from service.services.simulations.failure_codes import (
    executor_failure_code,
    feedback_failure_diagnostics,
)
from service.services.simulations.inputs.fragment_package import stage_fragment_package
from service.services.simulations.inputs.fragment_source import owned_fragment_source
from service.services.simulations.inputs.replay_source import owned_replay_source
from service.services.simulations.inputs.replay_transfer import stage_replay_input
from service.services.simulations.manifests.field_graph_manifest import (
    InvalidFieldGraphManifest,
    validate_field_graph_manifest,
    validate_field_graph_preview,
)
from service.services.simulations.manifests.field_proxy_manifest import (
    InvalidFieldProxyManifest,
    validate_field_proxy_manifest,
    validate_field_proxy_preview,
)
from service.services.simulations.manifests.fragment_population_manifest import (
    InvalidFragmentPopulationManifest,
    validate_fragment_population_manifest,
    validate_fragment_population_preview,
)
from service.services.simulations.manifests.manifest import InvalidManifest, validate_manifest
from service.services.simulations.manifests.population_feedback_manifest import (
    InvalidPopulationFeedbackManifest,
    validate_population_feedback_manifest,
    validate_population_feedback_preview,
)
from service.services.simulations.manifests.population_target_manifest import (
    InvalidPopulationTargetManifest,
    validate_population_target_manifest,
    validate_population_target_preview,
)
from service.services.simulations.manifests.replay_manifest import (
    InvalidReplayManifest,
    validate_replay_manifest,
    validate_replay_preview,
)
from service.services.simulations.models import SimulationArtifact, SimulationAttempt, SimulationRun
from service.services.simulations.progress import valid_progress
from service.services.simulations.runtime import file_service, generator_client, simulation_queue
from service.settings import config

logger = logging.getLogger(__name__)
TERMINAL = {"completed", "cancelled", "failed"}


class LostClaim(Exception):
    pass


async def emit(infra, run_id, state, progress=None):
    if infra.redis_client:
        try:
            async with asyncio.timeout(1):
                await infra.redis_client.xadd(
                    f"simulation:{run_id}:events",
                    {
                        "data": json.dumps(
                            {
                                "run_id": str(run_id),
                                "state": state,
                                "time": datetime.now(UTC).isoformat(),
                                **({"progress": progress} if progress is not None else {}),
                            }
                        )
                    },
                    maxlen=1000,
                )
                await infra.redis_client.expire(f"simulation:{run_id}:events", 86400)
                # Cache is disposable, never the authoritative run record.
                await infra.redis_client.setex(f"simulation:{run_id}:status", 60, state)
        except Exception:
            logger.warning("simulation_event_unavailable", extra={"run_id": str(run_id)})


async def touch(infra, run_id, token, state=None, result=None, error=None):
    async with infra.pg_connector.get_session_context() as session:
        run = (
            await session.execute(
                select(SimulationRun).where(SimulationRun.id == run_id).with_for_update()
            )
        ).scalar_one()
        if run.claim_token != token:
            raise LostClaim()
        cancelled = run.state == "cancelling"
        if state:
            if cancelled and state != "cancelled":
                return True
            run.state = state
        run.lease_until = datetime.now(UTC) + timedelta(seconds=30)
        if result is not None:
            run.result = result
        if error is not None:
            run.error = error
        elif state == "completed":
            run.error = None
        if run.state in TERMINAL:
            run.lease_until = None
            job = await session.get(UserLaunch, run.job_id)
            job.status = (
                ProcessingStatus.SUCCESS if run.state == "completed" else ProcessingStatus.FAILURE
            )
            job.celery_status = run.state
            attempt = (
                await session.get(SimulationAttempt, run.attempt_id) if run.attempt_id else None
            )
            if attempt:
                attempt.state = run.state
        await session.commit()
    if state:
        await emit(infra, run_id, "cancelling" if cancelled and state != "cancelled" else state)
    return cancelled


async def discard_unpublished(client, attempt_id, digest):
    response = await client.post(
        f"/v1/executions/{attempt_id}/discard", json={"configuration_sha256": digest}
    )
    if response.status_code != 404:
        response.raise_for_status()


async def discard_staged_target(client, attempt_id, payload):
    if 'source_package_sha256' not in payload:
        return
    response = await client.delete(f'/v1/replay-inputs/{attempt_id}',
        headers={'X-Content-SHA256': payload['source_package_sha256']})
    if response.status_code != 404:
        response.raise_for_status()


async def stage_target_with_lease(infra, client, run_id, token, attempt_id, source, payload):
    async def heartbeat():
        while True:
            await asyncio.sleep(10)
            await touch(infra, run_id, token)
    task = asyncio.create_task(heartbeat())
    try:
        return await stage_fragment_package(infra.storage, client, attempt_id, source,
            expected_package_sha=payload['source_package_sha256'],
            expected_manifest_sha=payload['source_manifest_sha256'])
    finally:
        task.cancel()
        results = await asyncio.gather(task, return_exceptions=True)
        if results and isinstance(results[0], Exception):
            raise results[0]


async def read_verified_preview(client, attempt_id, name, item):
    """Read a manifest-bounded preview without trusting the response body size."""
    data = bytearray()
    async with client.stream("GET", f"/v1/executions/{attempt_id}/artifacts/{name}") as stream:
        if stream.status_code == 404:
            raise InvalidManifest("artifact_missing")
        stream.raise_for_status()
        async for chunk in stream.aiter_bytes():
            if len(data) + len(chunk) > item["bytes"]:
                raise InvalidManifest("preview_integrity")
            data.extend(chunk)
    if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise InvalidManifest("preview_integrity")
    try:
        return json.loads(data)
    except (UnicodeDecodeError, ValueError) as exc:
        raise InvalidManifest("preview_invalid") from exc


async def discard_staged_replay(infra, client, attempt_id, owner, payload):
    """Remove an upload that may have preceded creation of an executor receipt."""
    if "source_run_id" not in payload:
        return
    async with infra.pg_connector.get_session_context() as session:
        source = await owned_replay_source(
            session, owner, UUID(payload["source_run_id"]), payload["graph_manifest_sha256"]
        )
    response = await client.delete(
        f"/v1/replay-inputs/{attempt_id}", headers={"X-Content-SHA256": source.sha256}
    )
    response.raise_for_status()


async def acknowledge_result(infra, client, run_id, attempt_id, digest):
    response = await client.post(
        f"/v1/executions/{attempt_id}/ack", json={"configuration_sha256": digest}
    )
    response.raise_for_status()
    async with infra.pg_connector.get_session_context() as session:
        run = (
            await session.execute(
                select(SimulationRun).where(SimulationRun.id == run_id).with_for_update()
            )
        ).scalar_one()
        if run.state == "completed" and run.attempt_id == attempt_id:
            run.result = {**run.result, "executor_acknowledged": True}
            await session.commit()


async def confirm_discard(infra, client, run_id, attempt_id, digest):
    await discard_unpublished(client, attempt_id, digest)
    async with infra.pg_connector.get_session_context() as session:
        run = (
            await session.execute(
                select(SimulationRun).where(SimulationRun.id == run_id).with_for_update()
            )
        ).scalar_one()
        if run.state in {"failed", "cancelled"} and run.attempt_id == attempt_id:
            run.result = {**(run.result or {}), "executor_discard_pending": False}
            await session.commit()


async def reject_result(infra, run_id, token, attempt_id, digest, reason):
    # Persist the intent in the same transaction as failure. A lost response or
    # process restart must not turn terminal state into an orphaned scratch dir.
    cancelled = await touch(
        infra,
        run_id,
        token,
        "failed",
        result={"executor_discard_pending": True},
        error="invalid_executor_manifest:" + reason,
    )
    try:
        async with generator_client() as client:
            if cancelled:
                await discard_unpublished(client, attempt_id, digest)
                await touch(infra, run_id, token, "cancelled")
            else:
                await confirm_discard(infra, client, run_id, attempt_id, digest)
    except Exception:
        logger.warning("simulation_invalid_output_cleanup_deferred", extra={"run_id": str(run_id)})


async def retry_interrupted(infra, run_id, token):
    async with infra.pg_connector.get_session_context() as session:
        run = (
            await session.execute(
                select(SimulationRun).where(SimulationRun.id == run_id).with_for_update()
            )
        ).scalar_one()
        if run.claim_token != token:
            raise LostClaim()
        previous = await session.get(SimulationAttempt, run.attempt_id)
        previous.state = "interrupted"
        if previous.number >= 3:
            return False
        run.attempt_id = uuid4()
        session.add(
            SimulationAttempt(
                id=run.attempt_id,
                run_id=run.id,
                number=previous.number + 1,
                state="preparing",
                executor="generator-primary",
            )
        )
        run.state = "cancelling" if run.state == "cancelling" else "queued"
        run.claim_token, run.lease_until, run.dispatched_at = None, None, None
        run.error = "executor_interrupted_retry_pending"
        await session.commit()
    return True


async def execute(run_id: UUID):
    infra = build_infra(config)
    token = uuid4()
    try:
        async with infra.pg_connector.get_session_context() as session:
            run = (
                await session.execute(
                    select(SimulationRun).where(SimulationRun.id == run_id).with_for_update()
                )
            ).scalar_one_or_none()
            if run is None or run.state in TERMINAL:
                return
            if run.execution_queue != simulation_queue():
                logger.warning("simulation_wrong_execution_queue", extra={"run_id": str(run_id)})
                return
            if run.lease_until and run.lease_until > datetime.now(UTC):
                return
            run.claim_token, run.lease_until = token, datetime.now(UTC) + timedelta(seconds=30)
            if run.attempt_id is None:
                run.attempt_id = uuid4()
                session.add(
                    SimulationAttempt(
                        id=run.attempt_id,
                        run_id=run.id,
                        number=1,
                        state="preparing",
                        executor="generator-primary",
                    )
                )
            attempt_id, owner, payload, digest, parent_id = (
                run.attempt_id,
                run.user_id,
                run.configuration,
                run.configuration_sha256,
                getattr(run, 'parent_run_id', None),
            )
            if run.state != "cancelling":
                run.state = "preparing"
            claimed_state = run.state
            job = await session.get(UserLaunch, run.job_id)
            job.status = ProcessingStatus.PROCESSING
            await session.commit()
        await emit(infra, run_id, claimed_state)
        async with generator_client() as client:
            if await touch(infra, run_id, token):
                # A redelivered task may find an already running remote attempt.
                await discard_unpublished(client, attempt_id, digest)
                await discard_staged_replay(infra, client, attempt_id, owner, payload)
                await discard_staged_target(client, attempt_id, payload)
                await touch(infra, run_id, token, "cancelled")
                return
            replay = "source_run_id" in payload
            field_graph = "source_cells" in payload and "replay_ids" in payload
            field_proxy = ('gain' in payload and 'waveform' in payload
                           and payload.get('coordinate_frame') == 'male-cns-v1.0-native-um')
            fragment_population = "source_ids" in payload and "max_distance_um" in payload
            population_target = 'source_package_sha256' in payload and 'target_id' in payload
            population_feedback = ('source_package_sha256' in payload
                                   and 'excitatory' in payload and 'inhibitory' in payload)
            source_configuration = None
            if replay:
                async with infra.pg_connector.get_session_context() as session:
                    source = await owned_replay_source(
                        session, owner, UUID(payload["source_run_id"]),
                        payload["graph_manifest_sha256"],
                    )
                await stage_replay_input(infra.storage, client, attempt_id, source)
                if await touch(infra, run_id, token):
                    await discard_unpublished(client, attempt_id, digest)
                    await discard_staged_replay(infra, client, attempt_id, owner, payload)
                    await touch(infra, run_id, token, "cancelled")
                    return
                response = await client.post("/v1/replay-executions", json={
                    "execution_id": str(attempt_id), "config": payload,
                    "source_sha256": source.sha256, "source_description": source.description,
                })
            elif population_target or population_feedback:
                if parent_id is None:
                    raise InvalidManifest('target_source_missing')
                async with infra.pg_connector.get_session_context() as session:
                    target_source = await owned_fragment_source(
                        session, owner, parent_id, payload['graph_manifest_sha256'])
                source_configuration = target_source.configuration
                await stage_target_with_lease(infra, client, run_id, token, attempt_id,
                                              target_source, payload)
                if await touch(infra, run_id, token):
                    await discard_unpublished(client, attempt_id, digest)
                    await discard_staged_target(client, attempt_id, payload)
                    await touch(infra, run_id, token, 'cancelled')
                    return
                endpoint = ('/v1/population-feedback-executions' if population_feedback
                            else '/v1/population-target-executions')
                response = await client.post(endpoint,
                    json={'execution_id': str(attempt_id), 'config': payload})
            elif field_proxy:
                response = await client.post(
                    '/v1/field-proxy-executions',
                    json={'execution_id': str(attempt_id), 'config': payload},
                )
            elif field_graph:
                response = await client.post(
                    "/v1/field-graph-executions",
                    json={"execution_id": str(attempt_id), "config": payload},
                )
            elif fragment_population:
                response = await client.post(
                    '/v1/fragment-population-executions',
                    json={'execution_id': str(attempt_id), 'config': payload},
                )
            else:
                response = await client.post(
                    "/v1/executions", json={"execution_id": str(attempt_id), "config": payload}
                )
            if response.status_code in {404, 422}:
                # A previous delivery may already have created this attempt.
                # Check that receipt before treating a validation rejection as final.
                existing = await client.get(f"/v1/executions/{attempt_id}")
                if existing.status_code == 404:
                    await discard_staged_replay(infra, client, attempt_id, owner, payload)
                    await discard_staged_target(client, attempt_id, payload)
                    reason = ("executor_endpoint_missing" if response.status_code == 404
                              else "executor_contract_rejected")
                    if await touch(infra, run_id, token, "failed",
                                   error=reason):
                        await touch(infra, run_id, token, "cancelled")
                    return
                existing.raise_for_status()
                receipt = existing.json()
                if (not isinstance(receipt, dict)
                        or receipt.get("configuration_sha256") != digest):
                    if await touch(infra, run_id, token, "failed",
                                   error="executor_attempt_identity"):
                        await touch(infra, run_id, token, "cancelled")
                    return
            else:
                response.raise_for_status()
            await touch(infra, run_id, token, "running")
            last_progress = None
            while True:
                if await touch(infra, run_id, token):
                    await discard_unpublished(client, attempt_id, digest)
                    await touch(infra, run_id, token, "cancelled")
                    return
                response = await client.get(f"/v1/executions/{attempt_id}")
                response.raise_for_status()
                status = response.json()
                progress = status.get('progress')
                if valid_progress(progress) and progress != last_progress:
                    await emit(infra, run_id, 'running', progress=progress)
                    last_progress = progress.copy()
                if status["status"] == "completed":
                    break
                if status["status"] in {"failed", "cancelled", "interrupted"}:
                    await discard_unpublished(client, attempt_id, digest)
                    if status["status"] == "interrupted" and await retry_interrupted(
                        infra, run_id, token
                    ):
                        return
                    diagnostic = (
                        feedback_failure_diagnostics(status, payload)
                        if population_feedback else None
                    )
                    await touch(infra, run_id, token, "failed", error=executor_failure_code(status),
                                result={'feedback_failure': diagnostic} if diagnostic else None)
                    return
                await asyncio.sleep(0.5)
            if await touch(infra, run_id, token, "publishing"):
                await discard_unpublished(client, attempt_id, digest)
                await touch(infra, run_id, token, "cancelled")
                return
            manifest = status["manifest"]
            if replay:
                try:
                    validate_replay_manifest(
                        manifest, configuration_sha256=digest,
                        source_run_id=UUID(payload["source_run_id"]),
                    )
                except InvalidReplayManifest as exc:
                    raise InvalidManifest(str(exc)) from exc
            elif population_feedback:
                try:
                    validate_population_feedback_manifest(manifest, configuration_sha256=digest,
                                                          configuration=payload)
                except InvalidPopulationFeedbackManifest as exc:
                    raise InvalidManifest('feedback_manifest') from exc
            elif population_target:
                try:
                    validate_population_target_manifest(manifest, configuration_sha256=digest)
                except InvalidPopulationTargetManifest as exc:
                    raise InvalidManifest('target_manifest') from exc
            elif field_proxy:
                try:
                    validate_field_proxy_manifest(manifest, configuration_sha256=digest)
                except InvalidFieldProxyManifest as exc:
                    raise InvalidManifest('field_proxy_manifest') from exc
            elif field_graph:
                try:
                    validate_field_graph_manifest(
                        manifest, configuration_sha256=digest,
                        retain_currents=payload.get("retain_currents") is True,
                        retain_state_contrast=payload.get("retain_state_contrast") is True,
                    )
                except InvalidFieldGraphManifest as exc:
                    raise InvalidManifest(str(exc)) from exc
            elif fragment_population:
                try:
                    validate_fragment_population_manifest(
                        manifest, configuration_sha256=digest,
                        graph_sha256=payload['graph_manifest_sha256'],
                    )
                except (InvalidFragmentPopulationManifest, KeyError) as exc:
                    raise InvalidManifest('fragment_manifest') from exc
            else:
                validate_manifest(manifest, payload, digest)
            saver = file_service(infra)
            for item in manifest["files"]:
                name = item["name"]
                if "/" in name or "\\" in name or name in {".", ".."}:
                    raise InvalidManifest("artifact_identity")
                async with infra.pg_connector.get_session_context() as session:
                    prior = (
                        await session.execute(
                            select(SimulationArtifact).where(
                                SimulationArtifact.run_id == run_id, SimulationArtifact.name == name
                            )
                        )
                    ).scalar_one_or_none()
                if prior:
                    if prior.sha256 != item["sha256"] or prior.size != item["bytes"]:
                        raise InvalidManifest("artifact_integrity")
                    continue

                async def verify_publication():
                    if await touch(infra, run_id, token):
                        raise LostClaim("run_cancelled")

                async with client.stream(
                    "GET", f"/v1/executions/{attempt_id}/artifacts/{name}"
                ) as stream:
                    if stream.status_code == 404:
                        raise InvalidManifest("artifact_missing")
                    stream.raise_for_status()
                    try:
                        saved = await saver.save_stream(
                            owner,
                            ServiceType.SIMULATION,
                            name,
                            stream.aiter_bytes(),
                            expected_size=item["bytes"],
                            expected_sha256=item["sha256"],
                            upload_intent_id=uuid5(run_id, name),
                            before_persist=verify_publication,
                        )
                    except ValueError as exc:
                        if str(exc) in {"artifact_integrity", "artifact_too_large"}:
                            raise InvalidManifest(str(exc)) from exc
                        raise
                async with infra.pg_connector.get_session_context() as session:
                    current = (
                        await session.execute(
                            select(SimulationRun)
                            .where(SimulationRun.id == run_id)
                            .with_for_update()
                        )
                    ).scalar_one()
                    if current.claim_token != token or current.state == "cancelling":
                        raise LostClaim()
                    session.add(
                        SimulationArtifact(
                            run_id=run_id,
                            file_id=saved.file_id,
                            name=name,
                            sha256=item["sha256"],
                            size=item["bytes"],
                        )
                    )
                    await session.commit()
            # Preview is consumed only after its independently hashed file was saved.
            preview_name = ("replay-preview.json" if replay else
                            'coupled-preview.json' if population_feedback else
                            'target-preview.json' if population_target else
                            'field-proxy-preview.json' if field_proxy else
                            "field-graph-preview.json" if field_graph else
                            'fragment-population-preview.json' if fragment_population else
                            "preview.json")
            preview_info = next(x for x in manifest["files"] if x["name"] == preview_name)
            preview = await read_verified_preview(client, attempt_id, preview_name, preview_info)
            try:
                if replay:
                    validate_replay_preview(preview, payload)
                elif population_feedback:
                    validate_population_feedback_preview(preview, payload, source_configuration)
                elif population_target:
                    validate_population_target_preview(preview, payload, source_configuration)
                elif field_proxy:
                    validate_field_proxy_preview(preview, payload)
                elif field_graph:
                    validate_field_graph_preview(preview, payload)
                elif fragment_population:
                    validate_fragment_population_preview(preview, payload)
            except (ValueError, InvalidReplayManifest, InvalidFieldGraphManifest,
                    InvalidFragmentPopulationManifest, InvalidPopulationTargetManifest,
                    InvalidPopulationFeedbackManifest, InvalidFieldProxyManifest) as exc:
                raise InvalidManifest("preview_invalid") from exc
            result = {
                "manifest": manifest,
                "preview": preview,
                "executor_acknowledged": False,
            }
            if await touch(infra, run_id, token, "completed", result=result):
                await discard_unpublished(client, attempt_id, digest)
                await touch(infra, run_id, token, "cancelled")
                return
            await acknowledge_result(infra, client, run_id, attempt_id, digest)
    except InvalidManifest as exc:
        await reject_result(infra, run_id, token, attempt_id, digest, str(exc))
    except LostClaim:
        # Another attempt or an explicit cancellation owns publication. No late SUCCESS.
        logger.info("simulation_claim_lost", extra={"run_id": str(run_id)})
    except Exception:
        logger.exception("simulation_attempt_unavailable", extra={"run_id": str(run_id)})
        try:
            async with infra.pg_connector.get_session_context() as session:
                run = (
                    await session.execute(
                        select(SimulationRun).where(SimulationRun.id == run_id).with_for_update()
                    )
                ).scalar_one_or_none()
                if run and run.claim_token == token and run.state not in TERMINAL:
                    run.lease_until = None
                    run.error = "temporary_execution_or_publication_failure"
                    await session.commit()
        except Exception:
            logger.warning("simulation_recovery_deferred")
    finally:
        await infra.pg_connector.close()
        if infra.redis_client:
            await infra.redis_client.aclose()


@celery_app.task(name="service.services.simulations.tasks.execute_run", acks_late=True)
def execute_run(run_id: str):
    asyncio.run(execute(UUID(run_id)))


async def recover():
    infra = build_infra(config)
    try:
        async with infra.pg_connector.get_session_context() as session:
            rows = (
                (
                    await session.execute(
                        select(SimulationRun)
                        .where(
                            SimulationRun.execution_queue == simulation_queue(),
                            SimulationRun.state.not_in(TERMINAL),
                            or_(
                                SimulationRun.lease_until.is_(None),
                                SimulationRun.lease_until < datetime.now(UTC),
                            ),
                            or_(
                                SimulationRun.dispatched_at.is_(None),
                                SimulationRun.dispatched_at
                                < datetime.now(UTC) - timedelta(seconds=15),
                            ),
                        )
                        .limit(30)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            for run in rows:
                await asyncio.to_thread(
                    execute_run.apply_async, args=[str(run.id)], queue=simulation_queue()
                )
                run.dispatched_at = datetime.now(UTC)
            await session.commit()
        # Publication is durable before cleanup. Retry a lost ack without
        # regenerating or deleting the already published backend files.
        async with infra.pg_connector.get_session_context() as session:
            pending = (
                await session.execute(
                    select(
                        SimulationRun.id,
                        SimulationRun.attempt_id,
                        SimulationRun.configuration_sha256,
                    )
                    .where(
                        SimulationRun.execution_queue == simulation_queue(),
                        SimulationRun.state == "completed",
                        SimulationRun.result["executor_acknowledged"].as_boolean().is_not(True),
                    )
                    .limit(30)
                )
            ).all()
        async with generator_client() as client:
            for run_id, attempt_id, digest in pending:
                try:
                    await acknowledge_result(infra, client, run_id, attempt_id, digest)
                except Exception:
                    logger.warning("simulation_ack_deferred", extra={"run_id": str(run_id)})
        async with infra.pg_connector.get_session_context() as session:
            discarded = (
                await session.execute(
                    select(
                        SimulationRun.id,
                        SimulationRun.attempt_id,
                        SimulationRun.configuration_sha256,
                    )
                    .where(
                        SimulationRun.execution_queue == simulation_queue(),
                        SimulationRun.state.in_({"failed", "cancelled"}),
                        SimulationRun.result["executor_discard_pending"].as_boolean().is_(True),
                    )
                    .limit(30)
                )
            ).all()
        async with generator_client() as client:
            for run_id, attempt_id, digest in discarded:
                try:
                    await confirm_discard(infra, client, run_id, attempt_id, digest)
                except Exception:
                    logger.warning("simulation_discard_deferred", extra={"run_id": str(run_id)})
    finally:
        await infra.pg_connector.close()
        if infra.redis_client:
            await infra.redis_client.aclose()


@celery_app.task(name="service.services.simulations.tasks.recover_runs")
def recover_runs():
    asyncio.run(recover())
