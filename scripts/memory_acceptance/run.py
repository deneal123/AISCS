"""Платная dev-приёмка фактов, сжатия и MemOS; максимум 500 кредитов по замороженным тарифам."""

import argparse
import asyncio
import json
import logging
import time

import httpx
import redis
from sqlalchemy import text

from service.composition.container import build_container
from service.composition.state import set_current_container
from service.infrastructure.memory import reset_memory_integration_singleton
from service.infrastructure.memory.memos import MemOSMemoryIntegration
from service.services.analytics.application.memory.service import MemoryService
from service.services.analytics.persistence.memory_facts_repository import MemoryFactsRepository
from service.services.billing.application.frozen_pricing import freeze_pricing
from service.services.billing.application.pricing_service import PricingService
from service.services.billing.persistence.pricing_repository import PricingRepository
from service.services.chat.infrastructure.agent_context import load_memory_parts
from service.services.chat.infrastructure.context.summary import (
    gateway_summarizer,
    get_or_build_history_summary,
    read_cached_summary,
)
from service.settings import config
from service.shared.memory_outcomes import MemoryWriteResult

from .guard import PaidGuard


async def verify_gigachat(guard, report):
    report["stage"] = "gigachat_embedding"
    status, result = await asyncio.to_thread(
        guard.forward,
        "/v1/embeddings",
        {
            "model": "gigachat:Embeddings",
            "input": ["Проверка нормализации учёта эмбеддинга"],
            "encoding_format": "float",
        },
    )
    assert status == 200, "gigachat_embedding_receipt_unconfirmed"
    assert len(result["data"][0]["embedding"]) == 1024
    report["gigachat_embedding_verified"] = True


async def exercise(container, actor, report, ceiling, check_gigachat, embedding_only):
    headers = {"Authorization": "Bearer " + config.agents.llm_gateway_api_key}
    async with httpx.AsyncClient(timeout=10) as client:
        profile = await client.get("http://agents:8090/v1/memory/profile", headers=headers)
        profile.raise_for_status()
    pricing = await freeze_pricing(
        PricingService(
            PricingRepository(container.infra.pg_connector),
            config.billing,
        )
    )
    guard = PaidGuard(
        key=config.agents.llm_gateway_api_key,
        pricing=pricing,
        profile=profile.json(),
        ceiling=ceiling,
    )
    server = guard.start()
    config.agents.sidecar_url = "http://127.0.0.1:18096"
    config.agents.memos_base_url = "http://memos:18097"
    config.agents.memos_api_key = config.agents.llm_gateway_api_key
    reset_memory_integration_singleton()
    integration = MemOSMemoryIntegration(
        base_url="http://memos:18097",
        timeout=40,
        api_key=config.agents.llm_gateway_api_key,
    )
    repo = MemoryFactsRepository(container.infra.pg_connector)
    memory = MemoryService(integration=integration, facts_repo=repo)
    cache = redis.Redis.from_url(config.redis.dsn)
    thread = "memory-acceptance-" + actor
    scoped = "user:" + actor
    try:
        if embedding_only:
            await verify_gigachat(guard, report)
            report["stage"] = "passed"
            return
        report["stage"] = "facts"
        usage = {}
        await memory.extract_and_save_facts(
            actor,
            thread,
            [
                {
                    "role": "user",
                    "content": "Я инженер. Постоянно предпочитаю ответы на русском языке.",
                },
                {"role": "assistant", "content": "Возможно, вы врач и живёте в Париже."},
            ],
            usage_out=usage,
        )
        facts = await repo.list_facts(user_id=scoped)
        values = " ".join(f["fact_value"] for f in facts).lower()
        report["facts_saved"] = len(facts)
        assert facts and "инженер" in values and "русск" in values, "facts_missing"
        assert "париж" not in values and "врач" not in values, "assistant_guess_saved"
        context = await memory.get_memory_context(actor, query="Какой язык ответов я предпочитаю?")
        assert "русск" in context.lower(), "facts_not_recalled"

        report["stage"] = "summary"
        items = [{"role": "user", "content": "Код проекта — Лимонный маяк. Бюджет 42 рубля."}]
        items.extend(
            {"role": "assistant" if i % 2 else "user", "content": f"Шаг {i}: продолжаем проект."}
            for i in range(15)
        )
        summary = await get_or_build_history_summary(
            items=items,
            session_id=thread,
            redis_client=cache,
            max_tokens=256,
            summarizer=gateway_summarizer,
        )
        assert "42" in summary and "маяк" in summary.lower(), "summary_lost_constraints"
        assert await read_cached_summary(thread, cache) == summary, "summary_not_persisted"
        calls = len(guard.calls)
        assert (
            await get_or_build_history_summary(
                items=items,
                session_id=thread,
                redis_client=cache,
                max_tokens=256,
                summarizer=gateway_summarizer,
            )
            == summary
        )
        assert len(guard.calls) == calls, "summary_paid_repeat"
        report["summary_verified"] = True

        report["stage"] = "semantic_write"
        result = await memory.remember_conversation(
            actor, [{"role": "user", "content": summary}], metadata={"kind": "summary"}
        )
        assert result is MemoryWriteResult.CONFIRMED, "semantic_write_unconfirmed"
        report["stage"] = "semantic_search"
        started = time.perf_counter()
        facts_context, recalled = await load_memory_parts(
            actor,
            logging.getLogger(__name__),
            "Лимонный маяк, бюджет проекта 42 рубля",
        )
        report["context_read_ms"] = round((time.perf_counter() - started) * 1000)
        assert facts_context, "facts_context_missing"
        assert "42" in recalled and "маяк" in recalled.lower(), "semantic_recall_missing"
        report["semantic_verified"] = True
        if check_gigachat:
            await verify_gigachat(guard, report)
        report["stage"] = "passed"
    finally:
        report.update(
            credits_ceiling=guard.ceiling,
            credits_accounted=guard.used,
            unknown_cost_ceiling=guard.unknown,
            provider_calls=len(guard.calls),
            providers=sorted({c["provider"] for c in guard.calls}),
        )
        # Чистим только собственные синтетические записи, не аккаунты стенда.
        report["facts_cleaned"] = await repo.delete_all_facts(user_id=scoped)
        cleanup = await integration.forget_user(user_id=scoped)
        report["semantic_cleanup"] = cleanup.get("ok") is True
        async with container.infra.pg_connector.get_session_context() as db:
            remaining = await db.scalar(
                text("SELECT count(*) FROM profile.user_memory_facts WHERE user_id=:owner"),
                {"owner": scoped},
            )
            assert remaining == 0
        cache.delete(
            "gpthub:agents:summary:" + thread, "gpthub:agents:summary:" + thread + ":building"
        )
        cache.close()
        await asyncio.to_thread(server.shutdown)
        server.server_close()


async def main(actor, ceiling, check_gigachat, embedding_only):
    assert actor.startswith("memory-live-") and len(actor) < 80
    assert 0 < ceiling <= 500
    logging.disable(logging.CRITICAL)
    container = build_container(config)
    set_current_container(container)
    report = {"stage": "admission", "billing": "operator_acceptance_no_user_charge"}
    try:
        await exercise(container, actor, report, ceiling, check_gigachat, embedding_only)
    except Exception as error:
        report["failure"] = (
            str(error) if isinstance(error, AssertionError) else type(error).__name__
        )
    finally:
        await container.infra.pg_connector.close()
        if container.infra.redis_manager:
            await container.infra.redis_manager.close()
    print(json.dumps(report), flush=True)
    return 0 if report["stage"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-paid", action="store_true", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--credits-ceiling", type=int, default=500)
    parser.add_argument("--check-gigachat-embeddings", action="store_true")
    parser.add_argument("--embedding-only", action="store_true")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            main(
                args.actor,
                args.credits_ceiling,
                args.check_gigachat_embeddings,
                args.embedding_only,
            )
        )
    )
