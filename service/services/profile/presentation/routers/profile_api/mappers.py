from uuid import UUID

from service.services.profile.application.dto import (
    DeleteChatHistoryCommand,
    GetProfileOverviewQuery,
    ProfileOverviewResult,
    UpdateNotificationPrefsCommand,
    UpdateProfileCommand,
)
from service.services.profile.presentation.routers.profile_api.schemas import (
    NotificationPrefsRequest,
    ProfileResponse,
    ProfileUpdateRequest,
)


def to_get_profile_query(user_id: UUID) -> GetProfileOverviewQuery:
    return GetProfileOverviewQuery(user_id=user_id)


def to_update_profile_command(user_id: UUID, payload: ProfileUpdateRequest) -> UpdateProfileCommand:
    data = payload.model_dump(exclude_unset=True)
    return UpdateProfileCommand(user_id=user_id, **data)


def to_notification_prefs_command(
    user_id: UUID, payload: NotificationPrefsRequest
) -> UpdateNotificationPrefsCommand:
    # exclude_unset — непереданное поле должно остаться None («не трогать»), а не стать
    # False: иначе PATCH одного тумблера молча выключал бы второй.
    data = payload.model_dump(exclude_unset=True)
    return UpdateNotificationPrefsCommand(
        user_id=user_id,
        marketing=data.get("marketing_emails"),
        service=data.get("service_emails"),
    )


def to_delete_chat_history_command(user_id: UUID) -> DeleteChatHistoryCommand:
    return DeleteChatHistoryCommand(user_id=user_id)


def to_profile_response(result: ProfileOverviewResult, permissions: list[str]) -> ProfileResponse:
    return ProfileResponse(
        id=result.id,
        email=result.email,
        first_name=result.first_name,
        timezone=result.timezone,
        avatar_url=result.avatar_url,
        marketing_emails=result.marketing_emails,
        service_emails=result.service_emails,
        created_at=result.created_at,
        updated_at=result.updated_at,
        permissions=permissions,
    )
