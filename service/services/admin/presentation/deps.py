"""Общая admin-зависимость: доступ по env-bootstrap ИЛИ DB-флагу is_admin."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from service.composition.state import get_admin_service
from service.models.auth_models import AuthProfile
from service.settings import config
from service.shared.security.auth_checker import check_auth


async def require_admin(
    request: Request,
    profile: Annotated[AuthProfile, Depends(check_auth)],
) -> AuthProfile:
    """403, если пользователь не админ (ни env SERVICE__ADMIN_USER_IDS, ни DB is_admin).

    Если admin-сервис/контейнер недоступен — деградируем до env-проверки (как было).
    """
    try:
        is_admin = await get_admin_service(request).is_admin(profile.user_id)
    except Exception:
        is_admin = str(profile.user_id).lower() in config.service.admin_user_ids_set
    if not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return profile
