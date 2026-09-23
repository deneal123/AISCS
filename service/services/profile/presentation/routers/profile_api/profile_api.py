"""Profile API: user overview, updates, quota preview."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from service.composition.state import get_admin_service, get_profile_service
from service.models.auth_models import AuthProfile
from service.services.profile.application.profile_service import ProfileService
from service.services.profile.presentation.routers.profile_api.mappers import (
    to_delete_chat_history_command,
    to_get_profile_query,
    to_notification_prefs_command,
    to_profile_response,
    to_update_profile_command,
)
from service.services.profile.presentation.routers.profile_api.schemas import (
    NotificationPrefsRequest,
    ProfileResponse,
    ProfileUpdateRequest,
)
from service.settings import config
from service.shared.security.auth_checker import check_auth

logger = logging.getLogger(__name__)

profile_router = APIRouter(prefix="/api/profile")


async def _compute_permissions(user_id: Any, request: Request) -> list[str]:
    """Права пользователя для фронта: env-admin → datasets:cleanup; любой админ → admin.

    Admin-сервис резолвится из контейнера мягко: если его нет (напр. в тестах без
    контейнера) — деградируем до env-проверки, маршрут не падает.
    """
    perms: list[str] = []
    is_env_admin = str(user_id).lower() in config.service.admin_user_ids_set
    if is_env_admin:
        perms.append("datasets:cleanup")
    is_admin = is_env_admin
    try:
        is_admin = await get_admin_service(request).is_admin(user_id)
    except Exception:
        is_admin = is_env_admin
    if is_admin:
        perms.append("admin")
    return perms


@profile_router.get("/me", response_model=ProfileResponse)
async def get_profile(
    request: Request,
    auth_profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> ProfileResponse:
    try:
        result = await service.get_profile_overview(to_get_profile_query(auth_profile.user_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        ) from exc

    permissions = await _compute_permissions(result.id, request)
    return to_profile_response(result, permissions)


@profile_router.patch("/me", response_model=ProfileResponse)
async def update_profile(
    request: Request,
    payload: ProfileUpdateRequest,
    auth_profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> ProfileResponse:
    try:
        overview = await service.update_profile_details(
            to_update_profile_command(auth_profile.user_id, payload)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        ) from exc

    permissions = await _compute_permissions(overview.id, request)
    return to_profile_response(overview, permissions)


@profile_router.patch("/me/notifications", response_model=ProfileResponse)
async def update_notification_prefs(
    request: Request,
    payload: NotificationPrefsRequest,
    auth_profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> ProfileResponse:
    """Тумблеры писем. Отдельный роут, а не поля в PATCH /me: общий апдейт пишет
    фиксированный список колонок и не должен ходить в юридические записи о согласии.
    """
    try:
        overview = await service.update_email_preferences(
            to_notification_prefs_command(auth_profile.user_id, payload)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        ) from exc

    permissions = await _compute_permissions(overview.id, request)
    return to_profile_response(overview, permissions)


@profile_router.delete("/me/chat-history", status_code=204)
async def delete_my_chat_history(
    auth_profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> None:
    try:
        await service.delete_chat_history(to_delete_chat_history_command(auth_profile.user_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        ) from exc
    return None
