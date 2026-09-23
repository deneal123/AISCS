from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserProfileLogic(BaseModel):
    id: UUID
    email: str
    password_hash: str
    available_launches: int = 0
    first_name: str | None = None
    timezone: str | None = None
    avatar_url: str | None = None
    email_verified: bool = False
    verified_at: datetime | None = None
    is_active: bool = True
    # Почтовые предпочтения. Хранятся метками времени, а не флагами: «когда согласие было
    # дано» — обязательная часть самой записи о согласии (152-ФЗ), голого bool тут мало.
    marketing_consent_at: datetime | None = None
    unsubscribed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
