"""Одна согласованная генерация через настоящий worker, резерв и settlement dev."""

import asyncio
import hashlib
import json
import logging
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.worker_process import deliver, prefork_worker

ANCHOR = UUID("143f2048-0ee9-40e5-92dc-50c3a977e6d6")
MODEL = "black-forest-labs/flux-3-image"
TEXT_MODEL = "GigaChat-3-Lightning"
QUESTION = "Сгенерируй картинку: пушистый рыжий котик сидит на солнечном подоконнике."
STAGE = "preflight"


async def receipts(container, actor, job):
    async with container.infra.pg_connector.get_session_context() as db:
        launch = (
            (
                await db.execute(
                    text("SELECT status,payload FROM profile.user_launch WHERE id=:id"), {"id": job}
                )
            )
            .mappings()
            .one()
        )
        charges = (
            (
                await db.execute(
                    text(
                        "SELECT tokens,metadata FROM profile.billing_events "
                        "WHERE user_id=:actor AND event_type='usage' AND metadata->>'job_id'=:job"
                    ),
                    {"actor": actor, "job": str(job)},
                )
            )
            .mappings()
            .all()
        )
    metadata = launch["payload"].get("metadata") or {}
    files = metadata.get("generated_files") or []
    digest = None
    if len(files) == 1:
        content = await container.services.file_saver_service.read_chat_library_bytes(
            actor, UUID(files[0]["file_id"])
        )
        digest = hashlib.sha256(content).hexdigest()
    calls = [call for event in charges for call in event["metadata"].get("per_call", [])]
    return {
        "job_id": str(job),
        "status": launch["status"],
        "image_saved": bool(digest),
        "_artifact_digest": digest,
        "charge_events": len(charges),
        "credits": sum(int(event["metadata"].get("credits") or 0) for event in charges),
        "tokens": sum(int(event["tokens"] or 0) for event in charges),
        "image_receipts": sum(call.get("model") == MODEL for call in calls),
        "image_provider": next(
            (call.get("provider") for call in calls if call.get("model") == MODEL), None
        ),
        "fallback": metadata.get("fallback"),
    }


async def exercise(container):
    global STAGE
    from service.infrastructure.agents_client.sidecar_providers import (
        fetch_keys_version,
        fetch_provider_health,
    )
    from service.services.admin.application.provider_key_service import ProviderKeyService
    from service.services.billing.application.pricing_service import PricingService
    from service.services.billing.persistence.pricing_repository import PricingRepository
    from service.services.chat.persistence.chat_repository import ChatRepository
    from service.settings import config

    STAGE = "keys_ack"
    await ProviderKeyService().ensure_sidecar_keys()
    version = await fetch_keys_version(config)
    assert version is not None and version >= 0, "keys_not_acknowledged"
    STAGE = "catalog_read"
    await fetch_provider_health(config, only=["routerai", "gigachat"])
    async with httpx.AsyncClient(timeout=10) as client:
        ready = await client.get(
            "http://agents:8091/__image_acceptance__/metrics",
            headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key},
        )
        ready.raise_for_status()
        print(json.dumps({"stage": "catalog_observed", **ready.json()}), flush=True)
        assert ready.json()["flux_admitted"] and not ready.json()["flux_chat"]
        assert ready.json()["image_calls"] == 0

    STAGE = "existing_actor"
    async with container.infra.pg_connector.get_session_context() as db:
        actor = await db.scalar(
            text(
                'SELECT u.id FROM profile."user" u JOIN profile.user_launch j ON j.user_id=u.id '
                "WHERE j.id=:anchor AND u.is_admin AND u.is_active"
            ),
            {"anchor": ANCHOR},
        )
    assert actor, "existing_admin_unavailable"
    STAGE = "bounded_price_quote"
    quote = await PricingService(
        PricingRepository(container.infra.pg_connector), config.billing
    ).price_request(
        per_call_usage=[
            {"model": MODEL, "provider": "routerai", "prompt": 0, "completion": 1024},
            {"model": TEXT_MODEL, "provider": "gigachat", "prompt": 10000, "completion": 2000},
        ],
        tools=["image_gen"],
        is_complex=False,
    )
    assert 0 < quote.credits <= 10000, "operator_cost_ceiling"
    thread, job, task = uuid4(), uuid4(), uuid4()
    await ChatRepository(container.infra.pg_connector).create_thread(
        actor, "Проверка генерации котика FLUX", str(thread)
    )
    queue = "image-acceptance-" + uuid4().hex
    async with prefork_worker(config.pg.db, queue) as (app, _pid):
        async with container.infra.pg_connector.get_session_context() as db:
            await db.execute(
                text(
                    "INSERT INTO profile.user_launch"
                    "(id,user_id,type,status,payload,celery_task_id) "
                    "VALUES (:job,:actor,'CHAT','NEW',CAST(:body AS jsonb),:task)"
                ),
                {
                    "job": job,
                    "actor": actor,
                    "task": str(task),
                    "body": json.dumps({"thread_id": str(thread)}),
                },
            )
            await db.commit()
        print(
            json.dumps(
                {
                    "stage": "job_created",
                    "job_id": str(job),
                    "thread_id": str(thread),
                    "quote_ceiling": quote.credits,
                }
            ),
            flush=True,
        )
        STAGE = "single_delivery"
        await deliver(
            app,
            queue,
            {
                "job_id": str(job),
                "thread_id": str(thread),
                "user_id": str(actor),
                "text": QUESTION,
                "selected_model": TEXT_MODEL,
                "route_override": "image_gen",
                "memory_enabled": False,
                "planning": False,
                "multi_intent": False,
                "session_data": {"confirm_expensive_run": True},
            },
            task_id=str(task),
            timeout=300,
        )
    STAGE = "read_receipts"
    result = await receipts(container, actor, job)
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(
            "http://agents:8091/__image_acceptance__/metrics",
            headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key},
        )
        response.raise_for_status()
        result.update(response.json())
    result["artifact_matches_provider"] = result.pop("_artifact_digest") == result.pop(
        "image_sha256"
    )
    print(json.dumps(result), flush=True)
    assert result["image_calls"] == 1 and result["image_saved"], "image_not_verified"
    assert result["dimensions"] and result["artifact_matches_provider"]
    assert result["charge_events"] == result["image_receipts"] == 1
    assert result["image_provider"] == "routerai" and not result["fallback"]


async def main():
    logging.disable(logging.CRITICAL)
    from service.composition.container import build_container
    from service.composition.state import set_current_container
    from service.settings import config

    assert not config.pg.db.startswith("gpthub_acceptance_")
    config.agents.sidecar_url = "http://agents:8091"
    container = build_container(config)
    set_current_container(container)
    try:
        await exercise(container)
    finally:
        await container.infra.pg_connector.close()
        if container.infra.redis_manager:
            await container.infra.redis_manager.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(json.dumps({"stage": STAGE, "error": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
