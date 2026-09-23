"""`POST /providers/keys` — приём снимка провайдерских ключей от backend.

Сайдкар — единственный, кто провайдерам звонит, поэтому ключи применяются здесь.
Здоровье тех же провайдеров живёт рядом (`health.py`): это разные операции с разной
ценой и разными правами, и раньше они делили один файл только по префиксу пути.

⚠️ `KEYS_VERSION` объявлен ЗДЕСЬ и читается сервисным `/health` — по нему backend
понимает, что снимок надо запушить заново (например, сайдкар перезапустился и
override'ы потерял).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from service.presentation import runtime
from service.presentation.deps import internal_auth
from service.schemas.providers import ProviderKeysSnapshot

router = APIRouter(prefix="/providers")
logger = logging.getLogger(__name__)

# Версия применённого набора провайдерских ключей. Backend сверяет её со своей и пушит
# снимок при расхождении — так лечится и рестарт сайдкара (override'ы теряются, версия
# обнуляется, backend видит расхождение и пушит заново).
KEYS_VERSION = -1


@router.post("/keys")
async def keys(
    payload: ProviderKeysSnapshot, authorization: str | None = Header(default=None)
) -> dict:
    """Принять снимок провайдерских ключей от backend'а.

    Зачем вообще: ключи, заменённые админом, лежат в БД backend'а, а LLM-вызовы после
    флипа делает САЙДКАР — у которого ни PG, ни Redis. До этого эндпоинта смена ключа до
    него не доезжала, и он молча продолжал бить старым ключом из env.

    Снимок применяется ЦЕЛИКОМ: провайдера нет в ``overrides`` → override снимается и
    ключ снова берётся из env. Так же лечится и рестарт сайдкара (он теряет override'ы).

    ⚠️ ЗДЕСЬ ЦЕНА ОШИБКИ АВТОРИЗАЦИИ ВЫШЕ, ЧЕМ ГДЕ-ЛИБО: эта ручка ПРИНИМАЕТ ключи
    провайдеров. До перевода на `internal_auth` она проверялась функцией шлюза `/v1`, у
    которой ПУСТОЙ ключ означает «пропустить всех» (dev-режим). То есть при
    незаполненном `AGENTS__LLM_GATEWAY_API_KEY` кто угодно из внутренней сети мог
    подменить платформе ключи провайдеров — направить трафик на свой ключ или снести
    override'ы. Теперь пустой ключ — отказ (503), а не открытая дверь.

    ⚠️ И вторая половина той же беды: проверка шлюза отдаёт 404 при выключенном
    `llm_gateway_enabled`. Выключение ЧУЖОЙ функции гасило приём ключей, а backend видел
    404 и молча считал, что не доехало.

    В ответе и в логах — только ИМЕНА провайдеров.
    """
    global KEYS_VERSION
    internal_auth(authorization)
    try:
        from service.domain.client import rebuild_provider_generation
        from service.domain.client.providers import credentials as pc
    except Exception:  # noqa: BLE001 — движок не подан
        return JSONResponse(
            status_code=503,
            content={"error": "engine_unavailable", "detail": "unavailable"},
        )

    applied: list[str] = []
    for provider in sorted(runtime.known_provider_names()):
        desired = payload.overrides.get(provider)
        current = pc.get_override(provider)
        if desired and desired != current:
            pc.set_override(provider, desired)
            await rebuild_provider_generation(provider)
            applied.append(provider)
        elif not desired and current is not None:
            pc.clear_override(provider)
            await rebuild_provider_generation(provider)
            applied.append(provider)

    KEYS_VERSION = int(payload.version)
    # Логируем ИМЕНА, никогда значения.
    if applied:
        logger.info("provider keys applied from backend: %s (version %s)", applied, KEYS_VERSION)
    return {"applied": applied, "version": KEYS_VERSION, "known": payload.provider_names()}
