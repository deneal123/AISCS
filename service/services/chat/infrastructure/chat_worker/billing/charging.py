"""Тарификация хода: списание за ответ, за роутер и за извлечение памяти.

🔴 ОТДЕЛЬНЫЙ УЗЕЛ, И ПРИЧИНА У НЕГО СВОЯ — ДЕНЬГИ. Оркестрация хода меняется, когда меняется
конвейер (контекст, движок, персист); эти функции — когда меняются правила оплаты: цена,
резерв, реституция, идемпотентность. Пока они лежали в одной функции с оркестрацией, файл
держался в полтора раза выше потолка, а денежная правка тонула среди сборки контекста.

⚠️ Побочные списания (роутер, память) идут БЕЗ РЕЗЕРВА и после основного — это осознанно
и названо здесь, чтобы не искать по всему воркеру: резерв держится на оценке ОСНОВНОГО
вызова, а эти два дешёвые и происходят уже по факту.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from functools import partial
from typing import Any

from service.services.billing.domain.charge_math import actually_charged
from service.services.chat.infrastructure.chat_worker.billing.quote import (
    UsagePricingInput,
    quote_usage,
)
from service.services.chat.infrastructure.chat_worker.billing.reservation.cleanup import (
    release_owned_hold,
)
from service.services.chat.infrastructure.chat_worker.billing.usage.provenance import (
    aggregate_provider,
)
from service.services.chat.infrastructure.chat_worker.harness.accounting import charge_if_owned
from service.services.chat.infrastructure.pricing_signals import _pricing_signals

logger = logging.getLogger(__name__)


def _overlay_billing(pg_connector, config):
    """Overlay-config биллинга для воркер-процесса (runtime-настройки из админки).

    Идемпотентно привязывает runtime_settings к этому процессу и возвращает
    OverlayBillingConfig. Fail-safe: при пустом overlay/недоступной БД — дефолты
    из статичного config.billing (поведение как до админки).
    """
    from service.services.admin.application.runtime_settings import (
        OverlayBillingConfig,
        runtime_settings,
    )
    from service.services.admin.persistence.app_settings_repository import AppSettingsRepository

    runtime_settings.ensure_bound(lambda: AppSettingsRepository(pg_connector))
    return OverlayBillingConfig(config.billing, runtime_settings)


async def _release_reservation(
    *, pg_connector, config, user_id: str | None, reservation_id: str | None
) -> None:
    """Отпустить неиспользованный резерв кредитов (best-effort, не роняет ответ)."""
    await release_owned_hold(
        pg_connector=pg_connector,
        config=config,
        user_id=user_id,
        reservation_id=reservation_id,
        overlay_billing=_overlay_billing,
    )


async def _observe_committed_spend(
    *, pg_connector: Any, redis_client: Any, user_id: str, credits: int, billing_cfg: Any
) -> None:
    """A post-charge signal cannot invalidate the already committed debit."""
    if credits <= 0 or redis_client is None:
        return
    try:
        from service.services.billing.application.abuse import accumulate_spend
        from service.services.billing.persistence.billing_repository import BillingRepository

        window = int(billing_cfg.abuse_spend_window_seconds)
        spent = await accumulate_spend(
            redis_client,
            user_id=user_id,
            credits=credits,
            window_seconds=window,
            now=datetime.now(UTC).timestamp(),
        )
        threshold = int(billing_cfg.abuse_spend_threshold_credits)
        if spent is not None and spent > threshold:
            await BillingRepository(pg_connector).record_flag(
                user_id=user_id,
                event_type="abuse_flag",
                metadata={"spent_window": spent, "window_sec": window, "threshold": threshold},
            )
    except Exception:
        logger.warning(
            "post-charge spend observation unavailable",
            extra={"component": "billing", "failure_code": "abuse_observation"},
        )


def _usage_calls(result, total_tokens, model):
    """Recover missing per-call attribution without applying a reservation floor."""
    calls = result.get("per_call_usage") or []
    if calls or total_tokens <= 0:
        return calls, False
    prompt = int(result.get("prompt_tokens") or 0)
    completion = int(result.get("completion_tokens") or 0)
    if prompt + completion <= 0:
        prompt, completion = total_tokens, 0
    logger.error(
        "billing usage breakdown reconstructed from bounded totals",
        extra={"component": "billing", "failure_code": "usage_breakdown_missing"},
    )
    return [{"model": str(model or ""), "prompt": prompt, "completion": completion}], True


async def _charge_usage(
    *,
    pg_connector,
    redis_client,
    user_id: str | None,
    execution_result: dict,
    thread_id: str,
    job_id: str,
    resolved_model: str | None,
    config,
    selected_model: str | None = None,
    reservation_id: str | None = None,
    reserved_estimate: int = 0,
    breakdown_out: dict | None = None,
    require_persisted: bool = False,
    pricing_inputs: tuple[bool, list[str]] | None = None,
) -> int:
    """Посчитать кредиты и списать их (подписка→докупка) + записать потребление.

    Кредиты считаются через PricingService (registry + маржа + сложность), затем
    BillingService.charge списывает баланс и пишет billing_event + usage_daily.
    Неблокирующе: любая ошибка (FK на анонима, недоступность БД) логируется и НЕ
    роняет ответ. НО НЕ fail-open по деньгам: если ответ пользователю отдан, а
    usage не пришёл от провайдера (total_tokens==0, напр. MWS-стрим) ИЛИ тарификация
    упала — списываем зарезервированную оценку (floor, ``reserved_estimate``, уже
    признанную подъёмной при reserve), а не отдаём генерацию даром. Списание 0 при
    отданном ответе логируется как аномалия (возможный бесплатный запрос).
    Если был резерв (``reservation_id``) — коммитится со списанием; если списания
    нет (нет ответа/юзера) — резерв отпускается. Идемпотентно по ``job_id``
    (редоставка Celery не задвоит списание). Возвращает фактически списанные кредиты.
    """
    harness_charge = await charge_if_owned(
        pg_connector, config, result=execution_result, user_id=user_id, job_id=job_id
    )
    if harness_charge is not None:
        return harness_charge
    release_hold = partial(
        _release_reservation,
        pg_connector=pg_connector,
        config=config,
        user_id=user_id,
        reservation_id=reservation_id,
    )
    try:
        total_tokens = int(execution_result.get("total_tokens") or 0)
        reply_produced = int(execution_result.get("reply_chars_count") or 0) > 0
        if not user_id:
            await release_hold()
            return 0

        metadata = execution_result.get("metadata")
        from service.services.chat.infrastructure.chat_worker.billing.acceptance import (
            failed_without_paid_work,
        )

        if failed_without_paid_work(execution_result, pricing_inputs):
            # Service refusal text cannot authorize the inference floor.
            await release_hold()
            return 0
        if (
            total_tokens <= 0
            and not execution_result.get("per_call_usage")
            and isinstance(metadata, dict)
            and metadata.get("document_outcome") == "failed"
            and metadata.get("document_failure_code") == "selected_model_unavailable"
        ):
            # A qualification refusal is deterministic service text, not an
            # accepted model response with missing usage. Do not charge the
            # reserved estimate for a call that never started.
            await release_hold()
            return 0

        from service.services.billing.application.billing_service import BillingService
        from service.services.billing.application.pricing_service import PricingService
        from service.services.billing.persistence.billing_repository import BillingRepository
        from service.services.billing.persistence.pricing_repository import PricingRepository

        # ⚠️ Дыра, которая не падает и не логируется сама. `per_call_usage` — единственный
        # источник цены, и читается он через `.get(...) or []`: потеряй сайдкар это поле —
        # цена станет `min_credits_per_request`, ОДИН кредит вместо тысяч. Ни одна проверка
        # не сработает: токены есть (флор не включится), кредит есть (warning молчит).
        #
        # ⚠️ Лога мало — он не возвращает деньги. Агрегаты (`prompt_tokens` и соседи) лежат
        # отдельными полями и потерю разбивки переживают, поэтому цену ВОССТАНАВЛИВАЕМ из
        # них, а не платим флор.
        per_call, per_call_reconstructed = _usage_calls(
            execution_result, total_tokens, resolved_model or selected_model
        )
        is_complex, tools = (
            pricing_inputs if pricing_inputs is not None else _pricing_signals(execution_result)
        )
        billing_cfg = _overlay_billing(pg_connector, config)

        quote = await quote_usage(
            UsagePricingInput(
                total_tokens=total_tokens,
                reply_produced=reply_produced,
                reserved_estimate=reserved_estimate,
                per_call_usage=per_call,
                chosen_model=resolved_model or selected_model,
                tools=tools,
                is_complex=is_complex,
                reconstructed=per_call_reconstructed,
            ),
            pricing_factory=lambda: PricingService(PricingRepository(pg_connector), billing_cfg),
            require_persisted=require_persisted,
            breakdown_out=breakdown_out,
        )
        if quote is None:
            await release_hold()
            return 0
        credits, raw_cost, billing_fallback = quote.credits, quote.raw_cost_rub, quote.fallback

        charge_metadata: dict[str, Any] = {
            "prompt": int(execution_result.get("prompt_tokens") or 0),
            "completion": int(execution_result.get("completion_tokens") or 0),
            "model": resolved_model,
            "thread_id": thread_id,
            "job_id": job_id,
            "per_call": per_call,
            "tools": tools,
            "is_complex": is_complex,
            # 🔴 Резерв — в историю рядом с фактом: по нему видно, насколько оценка разошлась
            # с ценой. Замер: в 579 списаниях dev-базы этого поля нет НИ У ОДНОГО.
            **({"reserved_estimate": int(reserved_estimate)} if reserved_estimate > 0 else {}),
        }
        tool_summary = execution_result.get("tool_summary") or {}
        if tool_summary.get("prompt_budget_reached"):
            charge_metadata.update(
                {
                    "stop_reason": "prompt_budget_reached",
                    "estimated_prompt_tokens": int(
                        tool_summary.get("estimated_prompt_tokens") or 0
                    ),
                    "prompt_budget_tokens": int(tool_summary.get("prompt_budget_tokens") or 0),
                }
            )
        provider = aggregate_provider(per_call)
        if provider:
            charge_metadata["provider"] = provider
        if billing_fallback:
            charge_metadata["billing_fallback"] = billing_fallback

        charge_result = await BillingService(BillingRepository(pg_connector), billing_cfg).charge(
            user_id,
            credits=credits,
            tokens=total_tokens,
            raw_cost_rub=raw_cost,
            reservation_id=reservation_id,
            idempotency_key=job_id,
            metadata=charge_metadata,
        )
        # Редоставка Celery-задачи: за этот job уже списывали (idempotency_key=job_id)
        # → в ЭТОЙ попытке денег не двигали. Возвращаем 0, иначе возможный refund при
        # последующем сбое вернул бы оригинальное (чужое для этой попытки) списание.
        if isinstance(charge_result, dict) and charge_result.get("idempotent"):
            logger.info(
                "duplicate charge skipped",
                extra={"component": "billing", "status": "idempotent"},
            )
            return 0

        # Наблюдаемость: списание 0 при отданном ответе — возможный бесплатный запрос
        # (не смогли ни оценить usage, ни зарезервировать флор). Не блокируем, логируем.
        if credits <= 0 and reply_produced:
            logger.warning(
                "zero-credit charge recorded despite a produced reply",
                extra={"component": "billing", "failure_code": "zero_charge"},
            )

        await _observe_committed_spend(
            pg_connector=pg_connector,
            redis_client=redis_client,
            user_id=user_id,
            credits=actually_charged(charge_result),
            billing_cfg=billing_cfg,
        )
        # 🔴 ФАКТ, А НЕ НОМИНАЛ: на этом числе висят реституция и стоимость хода для человека.
        return actually_charged(charge_result)
    except Exception:
        logger.debug(
            "usage charge failed",
            extra={"component": "billing", "failure_code": "charge"},
        )
        if require_persisted:
            raise RuntimeError("usage_charge_unavailable") from None
        return 0


async def _charge_memory_usage(
    *,
    pg_connector,
    redis_client,
    user_id: str | None,
    mem_usage: dict[str, Any],
    thread_id: str,
    job_id: str,
    config,
) -> int:
    """Тарифицировать LLM-вызов долговременной памяти (экстракция фактов).

    Экстракция идёт ОТДЕЛЬНЫМ вызовом уже ПОСЛЕ публикации ответа, поэтому её
    токены не попадают в основной ``_charge_usage``. Списываем их отдельным
    billing_event (без двойного начисления — свой per_call с моделью экстракции).
    Полностью неблокирующе: любая ошибка логируется в debug и НЕ влияет на ответ.
    """
    total = int((mem_usage or {}).get("total") or 0)
    if total <= 0 or not user_id:
        return 0
    prompt = int(mem_usage.get("prompt") or 0)
    completion = int(mem_usage.get("completion") or 0)
    model = str(mem_usage.get("model") or "")
    calls = mem_usage.get("calls")
    if isinstance(calls, list) and calls and all(isinstance(call, dict) for call in calls):
        per_call = [dict(call) for call in calls]
        models = {call.get("model") for call in per_call}
        model = next(iter(models)) if len(models) == 1 else None
    else:
        per_call = [{"model": model, "prompt": prompt, "completion": completion}]
    # Переиспользуем общий путь тарификации/списания: конструируем execution_result
    # только с usage памяти (без tools/complexity → базовая цена). reservation=None.
    mem_execution_result = {
        "total_tokens": total,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "per_call_usage": per_call,
    }
    return await _charge_usage(
        pg_connector=pg_connector,
        redis_client=redis_client,
        user_id=user_id,
        execution_result=mem_execution_result,
        thread_id=thread_id,
        job_id=f"{job_id}:memory",
        resolved_model=model or None,
        config=config,
        reservation_id=None,
    )


async def _charge_router_usage(
    *,
    pg_connector,
    redis_client,
    user_id: str | None,
    session_data: dict | None,
    thread_id: str,
    job_id: str,
    config,
) -> int:
    """Тарифицировать LLM-вызов роутера модели (аудит A2).

    Роутер срабатывает в ВЕБ-процессе (resolve_route) на каждое авто-сообщение, ДО
    воркера, поэтому его usage не попадает в основной ``_charge_usage``. Веб-процесс
    кладёт его в ``session_data['_router_usage']``; здесь списываем отдельным
    billing_event (свой per_call с моделью роутера, идемпотентно по ``job_id:router``).
    Полностью неблокирующе — как и память.
    """
    router_usage = (session_data or {}).get("_router_usage")
    if not isinstance(router_usage, dict):
        return 0
    total = int(router_usage.get("total") or 0)
    if total <= 0 or not user_id:
        return 0
    prompt = int(router_usage.get("prompt") or 0)
    completion = int(router_usage.get("completion") or 0)
    model = str(router_usage.get("model") or "")
    calls = router_usage.get("calls")
    if isinstance(calls, list) and calls and all(isinstance(call, dict) for call in calls):
        per_call = [dict(call) for call in calls]
        # A multi-model router stage has no single chosen answer model: do not
        # apply the answer-model substitution ceiling to its independent calls.
        models = {call.get("model") for call in per_call}
        model = next(iter(models)) if len(models) == 1 else None
    else:
        # Old route producers supplied only aggregates and a model label.
        per_call = [{"model": model, "prompt": prompt, "completion": completion}]
    router_execution_result = {
        "total_tokens": total,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "per_call_usage": per_call,
    }
    return await _charge_usage(
        pg_connector=pg_connector,
        redis_client=redis_client,
        user_id=user_id,
        execution_result=router_execution_result,
        thread_id=thread_id,
        job_id=f"{job_id}:router",
        resolved_model=model or None,
        config=config,
        reservation_id=None,
    )
