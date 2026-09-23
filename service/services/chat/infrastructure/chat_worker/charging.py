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
from typing import Any

from service.services.billing.domain.charge_math import actually_charged
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


async def _price_ceiling_for_chosen_model(
    *,
    pricing,
    per_call_usage: list[dict],
    chosen_model: str | None,
    tools: list,
    is_complex: bool,
) -> int | None:
    """Во сколько обошёлся бы ТОТ ЖЕ объём токенов по цене ВЫБРАННОЙ пользователем модели.

    Возвращает None, если считать не от чего (нет модели/вызовов) — тогда потолка нет.
    """
    if not chosen_model or not per_call_usage:
        return None
    substituted = [c for c in per_call_usage if str(c.get("model") or "") != str(chosen_model)]
    if not substituted:
        return None  # подмены не было — потолок не нужен
    as_chosen = [{**call, "model": chosen_model} for call in per_call_usage]
    price = await pricing.price_request(
        per_call_usage=as_chosen, tools=tools, is_complex=is_complex
    )
    return int(price.credits)


async def _release_reservation(*, pg_connector, config, reservation_id: str | None) -> None:
    """Отпустить неиспользованный резерв кредитов (best-effort, не роняет ответ)."""
    if not reservation_id:
        return
    try:
        from service.services.billing.application.billing_service import BillingService
        from service.services.billing.persistence.billing_repository import BillingRepository

        billing_cfg = _overlay_billing(pg_connector, config)
        await BillingService(BillingRepository(pg_connector), billing_cfg).release_reservation(
            reservation_id
        )
    except Exception:
        logger.debug(
            "credit reservation release failed",
            extra={"component": "billing", "failure_code": "reservation_release"},
        )


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
    try:
        total_tokens = int(execution_result.get("total_tokens") or 0)
        reply_produced = int(execution_result.get("reply_chars_count") or 0) > 0
        if not user_id:
            await _release_reservation(
                pg_connector=pg_connector, config=config, reservation_id=reservation_id
            )
            return 0

        from service.services.billing.application.billing_service import BillingService
        from service.services.billing.application.pricing_service import PricingService
        from service.services.billing.persistence.billing_repository import BillingRepository
        from service.services.billing.persistence.pricing_repository import PricingRepository

        per_call = execution_result.get("per_call_usage") or []
        # ⚠️ Дыра, которая не падает и не логируется сама. `per_call_usage` — единственный
        # источник цены, и читается он через `.get(...) or []`: потеряй сайдкар это поле —
        # цена станет `min_credits_per_request`, ОДИН кредит вместо тысяч. Ни одна проверка
        # не сработает: токены есть (флор не включится), кредит есть (warning молчит).
        #
        # ⚠️ Лога мало — он не возвращает деньги. Агрегаты (`prompt_tokens` и соседи) лежат
        # отдельными полями и потерю разбивки переживают, поэтому цену ВОССТАНАВЛИВАЕМ из
        # них, а не платим флор.
        per_call_reconstructed = False
        if total_tokens > 0 and not per_call:
            _prompt = int(execution_result.get("prompt_tokens") or 0)
            _completion = int(execution_result.get("completion_tokens") or 0)
            if _prompt + _completion <= 0:
                # Разбивки нет вовсе — всё в prompt: это ДЕШЁВАЯ половина тарифа, то есть
                # при неизвестном составе счёт не задирается сверх фактически известного.
                _prompt, _completion = total_tokens, 0
            per_call = [
                {
                    "model": str(resolved_model or selected_model or ""),
                    "prompt": _prompt,
                    "completion": _completion,
                }
            ]
            per_call_reconstructed = True
            logger.error(
                "billing usage breakdown reconstructed from bounded totals",
                extra={"component": "billing", "failure_code": "usage_breakdown_missing"},
            )
        is_complex, tools = _pricing_signals(execution_result)
        billing_cfg = _overlay_billing(pg_connector, config)

        billing_fallback: str | None = None
        if per_call_reconstructed:
            billing_fallback = "per_call_reconstructed"
        if total_tokens <= 0:
            # Провайдер не вернул usage. Ответ отдан → списываем резерв-флор (не даром);
            # ответа/резерва нет → отпускаем резерв и выходим.
            if not (reply_produced and reserved_estimate > 0):
                await _release_reservation(
                    pg_connector=pg_connector, config=config, reservation_id=reservation_id
                )
                return 0
            credits = int(reserved_estimate)
            raw_cost = 0.0
            billing_fallback = "no_provider_usage_floor"
        else:
            try:
                pricing = PricingService(PricingRepository(pg_connector), billing_cfg)
                price = await pricing.price_request(
                    per_call_usage=per_call, tools=tools, is_complex=is_complex
                )
                credits = price.credits
                raw_cost = float(price.raw_cost_rub)
                # Из чего сложился счёт — наружу, в подсказку под сообщением. Замер по
                # живому сообщению: 733 кредита за токены и 834 за надбавку веб-поиска,
                # то есть БОЛЬШЕ ПОЛОВИНЫ цены не имело отношения к показанным токенам.
                # ⚠️ Только здесь: ниже счёт может ужаться потолком подмены модели, и
                # тогда доля надбавки, посчитанная до потолка, к итогу не относится.
                if breakdown_out is not None and price.surcharge_credits > 0:
                    breakdown_out["surcharge_credits"] = int(price.surcharge_credits)
                    breakdown_out["surcharged_tools"] = list(tools)

                # Потолок цены по ВЫБРАННОЙ модели. Фейловер подставляет чужую, а человек
                # видит в UI свой выбор и платит за наш инцидент: живой случай — выбран
                # claude-haiku (fast), упал OpenRouter, подставился jamba-large, и те же
                # 17k токенов стоили 4505 кредитов вместо 396.
                #
                # Считаем те же токены по цене выбранной и берём минимум; разницу
                # поглощает платформа — дорогой фейловер должен бить по нам, тогда его
                # чинят. База — `resolved_model` (до фейловера), при None падаем на
                # `selected_model`: иначе потолка нет вовсе.
                capped = await _price_ceiling_for_chosen_model(
                    pricing=pricing,
                    per_call_usage=per_call,
                    chosen_model=resolved_model or selected_model,
                    tools=tools,
                    is_complex=is_complex,
                )
                if capped is not None and capped < credits:
                    logger.warning(
                        "provider substitution charge capped",
                        extra={"component": "billing", "failure_code": "model_substitution"},
                    )
                    billing_fallback = "model_substitution_capped"
                    credits = capped
                    # Потолок пересчитал счёт целиком — прежняя доля надбавки в него уже
                    # не укладывается. Лучше не показать разбивку, чем показать неверную.
                    if breakdown_out is not None:
                        breakdown_out.clear()
            except Exception:
                # Тарификация упала, но ответ отдан → не бесплатно: floor = резерв (если был).
                logger.warning(
                    "pricing failed; applying reserved floor",
                    extra={"component": "billing", "failure_code": "pricing"},
                )
                credits = int(reserved_estimate) if reserved_estimate > 0 else 0
                raw_cost = 0.0
                billing_fallback = "pricing_failed_floor" if credits > 0 else "pricing_failed_zero"

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
        provider_model = str((per_call[0] if per_call else {}).get("model") or resolved_model or "")
        provider = provider_model.partition(":")[0].partition("/")[0].lower()
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

        # Детекция аномальной скорости трат (флаг, не блокировка).
        if credits > 0 and redis_client is not None:
            from service.services.billing.application.abuse import accumulate_spend

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
        # 🔴 ФАКТ, А НЕ НОМИНАЛ: на этом числе висят реституция и стоимость хода для человека.
        return actually_charged(charge_result)
    except Exception:
        logger.debug(
            "usage charge failed",
            extra={"component": "billing", "failure_code": "charge"},
        )
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
    # Переиспользуем общий путь тарификации/списания: конструируем execution_result
    # только с usage памяти (без tools/complexity → базовая цена). reservation=None.
    mem_execution_result = {
        "total_tokens": total,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "per_call_usage": [{"model": model, "prompt": prompt, "completion": completion}],
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
    router_execution_result = {
        "total_tokens": total,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "per_call_usage": [{"model": model, "prompt": prompt, "completion": completion}],
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
