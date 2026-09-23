"""Admin API: runtime-настройки, пользователи, системная аналитика, тарифы.

Цены моделей и reconcile живут в admin_billing_router (/api/admin/billing/*) —
не дублируем. Здесь — настройки, пользователи, аналитика, обзор планов/паков.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from service.composition.state import (
    get_admin_service,
    get_billing_service,
    get_optional_redis_client,
)
from service.infrastructure.memory.memos import wipe_memos_memory
from service.infrastructure.messaging.user_events import (
    EVENT_BALANCE_REFRESH,
    publish_user_event,
)
from service.models.auth_models import AuthProfile
from service.services.admin.application.admin_service import AdminRoleError, SettingError
from service.services.admin.presentation.deps import require_admin
from service.services.billing.application.billing_service import BillingService

logger = logging.getLogger(__name__)
admin_router = APIRouter(prefix="/api/admin")


class SettingUpdateRequest(BaseModel):
    key: Annotated[str, Field(..., description="Ключ настройки из реестра")]
    value: Any = Field(..., description="Новое значение (тип по реестру)")


class AdjustCreditsRequest(BaseModel):
    delta: Annotated[int, Field(..., description="Изменение докуп-баланса (±)")]
    reason: str = Field("", description="Причина корректировки (в аудит)")


class SetRoleRequest(BaseModel):
    is_admin: Annotated[bool, Field(..., description="Назначить/снять админ-роль")]


class SetActiveRequest(BaseModel):
    is_active: Annotated[bool, Field(..., description="Активен (true) / заблокирован (false)")]


class SetPlanRequest(BaseModel):
    plan: Annotated[str, Field(..., description="Тариф (free/pro/enterprise)")]


class SetBalanceRequest(BaseModel):
    balance: Annotated[int, Field(..., ge=0, description="Новый докуп-баланс (абсолютно)")]
    reason: str = Field("", description="Причина (в аудит)")


class ProviderKeyRequest(BaseModel):
    api_key: Annotated[str, Field(..., min_length=1, description="Новый API-ключ провайдера")]


class MemosEmbedderRequest(BaseModel):
    model: Annotated[str, Field(..., min_length=1, description="Модель эмбеддера MemOS")]
    dimension: Annotated[int, Field(..., ge=64, le=8192, description="Размерность эмбеддера")]


def get_provider_key_service():
    from service.services.admin.application.provider_key_service import ProviderKeyService

    return ProviderKeyService()


# --- настройки ------------------------------------------------------------- #
@admin_router.get("/settings", summary="Effective runtime settings + registry")
async def get_settings(
    _: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
) -> dict:
    return await service.get_settings_view()


@admin_router.put("/settings", summary="Override a runtime setting")
async def put_setting(
    payload: SettingUpdateRequest,
    admin: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
) -> dict:
    try:
        return await service.set_setting(
            key=payload.key, value=payload.value, updated_by=str(admin.user_id)
        )
    except SettingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@admin_router.delete("/settings/{key}", summary="Reset a setting to env/default")
async def delete_setting(
    key: str,
    _: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
) -> dict:
    try:
        return await service.reset_setting(key=key)
    except SettingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# --- тарифы/паки (обзор; цены — в /api/admin/billing) ---------------------- #
@admin_router.get("/plans", summary="Plans & top-up packs (effective)")
async def get_plans(
    _: Annotated[AuthProfile, Depends(require_admin)],
    billing: Annotated[BillingService, Depends(get_billing_service)],
) -> dict:
    return billing.list_plans_and_packs()


# --- пользователи ---------------------------------------------------------- #
@admin_router.get("/users", summary="List/search users")
async def list_users(
    _: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    return await service.list_users(
        query=query, limit=min(max(limit, 1), 200), offset=max(offset, 0)
    )


@admin_router.get("/users/{user_id}", summary="User detail")
async def get_user(
    user_id: str,
    _: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
) -> dict:
    user = await service.get_user(user_id=user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@admin_router.get("/users/{user_id}/events", summary="User operations history (paginated)")
async def list_user_events(
    user_id: str,
    _: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
    limit: int = 20,
    offset: int = 0,
) -> dict:
    return await service.list_user_events(
        user_id=user_id, limit=min(max(limit, 1), 100), offset=max(offset, 0)
    )


@admin_router.post("/users/{user_id}/adjust-credits", summary="Adjust top-up credits (±, audited)")
async def adjust_credits(
    user_id: str,
    payload: AdjustCreditsRequest,
    admin: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
    redis_client: Annotated[Any, Depends(get_optional_redis_client)],
) -> dict:
    try:
        result = await service.adjust_credits(
            user_id=user_id,
            delta=payload.delta,
            reason=payload.reason,
            updated_by=str(admin.user_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    # ⚠️ ПОСЛЕ успешной записи, не вместо. Публикуем сигнал «баланс изменился» в
    # персональный канал пользователя, чтобы его открытая вкладка перечитала баланс
    # СРАЗУ, а не по таймеру фокуса. Fail-soft: pub/sub лёг — просто вернёмся к прежней
    # задержке, ронять успешное пополнение из-за уведомления нельзя.
    await publish_user_event(redis_client, user_id, EVENT_BALANCE_REFRESH)
    return result


@admin_router.post("/users/{user_id}/set-role", summary="Grant/revoke admin role")
async def set_role(
    user_id: str,
    payload: SetRoleRequest,
    _: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
) -> dict:
    try:
        ok = await service.set_role(user_id=user_id, is_admin=payload.is_admin)
    except AdminRoleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"status": "ok", "user_id": user_id, "is_admin": payload.is_admin, "updated": ok}


@admin_router.post("/users/{user_id}/set-active", summary="Block/unblock a user")
async def set_active(
    user_id: str,
    payload: SetActiveRequest,
    admin: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
) -> dict:
    try:
        return await service.set_active(
            user_id=user_id, is_active=payload.is_active, acting_admin_id=str(admin.user_id)
        )
    except AdminRoleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@admin_router.post("/users/{user_id}/set-plan", summary="Change a user's plan")
async def set_plan(
    user_id: str,
    payload: SetPlanRequest,
    _: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
) -> dict:
    try:
        return await service.set_plan(user_id=user_id, plan=payload.plan)
    except SettingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@admin_router.post("/users/{user_id}/set-balance", summary="Set top-up balance (absolute, audited)")
async def set_balance(
    user_id: str,
    payload: SetBalanceRequest,
    admin: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
    redis_client: Annotated[Any, Depends(get_optional_redis_client)],
) -> dict:
    try:
        result = await service.set_topup_credits(
            user_id=user_id,
            value=payload.balance,
            reason=payload.reason,
            updated_by=str(admin.user_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    # Второй путь пополнения — та же подсказка «перечитай баланс», см. adjust_credits.
    await publish_user_event(redis_client, user_id, EVENT_BALANCE_REFRESH)
    return result


# --- аналитика/наблюдаемость ----------------------------------------------- #
@admin_router.get("/analytics", summary="System-wide usage/revenue/abuse + provider status")
async def get_analytics(
    _: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
    range: str = "30d",
) -> dict:
    return await service.get_system_analytics(range_key=range)


@admin_router.get("/providers/health", summary="Last provider health snapshot (no live probe)")
async def get_providers_health(
    _: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
) -> dict:
    return await service.provider_health()


@admin_router.post("/providers/health/recheck", summary="Force live provider health check")
async def recheck_providers_health(
    _: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
) -> dict:
    """Живая проверка всех провайдеров по кнопке админа: недостижимые → блок (скрыты у
    юзеров, не пробуются), снова достижимые → разблок. Возвращает свежий снимок."""
    return await service.recheck_provider_health()


@admin_router.get("/providers/keys", summary="Provider API-key status (never returns keys)")
async def list_provider_keys(
    _: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_provider_key_service)],
) -> dict:
    """Статус ключей по провайдерам: настроен ли (override/env), кем/когда обновлён.
    Сами ключи наружу не отдаются никогда."""
    return {"providers": await service.list_status()}


@admin_router.put("/providers/{provider}/api-key", summary="Replace a provider API key at runtime")
async def set_provider_key(
    provider: str,
    payload: ProviderKeyRequest,
    admin: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_provider_key_service)],
) -> dict:
    """Заменить API-ключ провайдера без рестарта стека: шифруем в БД, пересобираем
    клиента и сигналим другим процессам через версию в Redis."""
    try:
        return await service.set_key(provider, payload.api_key, updated_by=str(admin.user_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.delete("/providers/{provider}/api-key", summary="Remove a provider key override")
async def delete_provider_key(
    provider: str,
    admin: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_provider_key_service)],
) -> dict:
    """Убрать override-ключ провайдера → возврат к ключу из окружения (env)."""
    try:
        return await service.delete_key(provider, updated_by=str(admin.user_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@admin_router.put("/memos/embedder", summary="Set MemOS embedder (model+dim) + wipe memory")
async def set_memos_embedder(
    payload: MemosEmbedderRequest,
    admin: Annotated[AuthProfile, Depends(require_admin)],
    service: Annotated[Any, Depends(get_admin_service)],
) -> dict:
    """Сменить эмбеддер MemOS: сохранить модель+размерность в настройки, ПОЛНОСТЬЮ
    сбросить память MemOS (коллекция Qdrant привязана к размерности). Новый эмбеддер
    применится после рестарта memos (сервис читает настройку при старте)."""
    try:
        await service.set_setting(
            key="agents.memos_embedder_model", value=payload.model, updated_by=str(admin.user_id)
        )
        await service.set_setting(
            key="agents.memos_embedder_dim",
            value=payload.dimension,
            updated_by=str(admin.user_id),
        )
    except SettingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    wipe = await wipe_memos_memory()
    return {
        "ok": True,
        "wipe": wipe,
        "note": "Память MemOS сброшена. Перезапустите memos, чтобы применить новый эмбеддер.",
    }


@admin_router.post("/memos/wipe", summary="Wipe all MemOS memory")
async def wipe_memos(
    _: Annotated[AuthProfile, Depends(require_admin)],
) -> dict:
    """Полный сброс памяти MemOS (все пользователи) — Neo4j + Qdrant."""
    return await wipe_memos_memory()
