from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, HttpUrl, model_validator


class ProfileResponse(BaseModel):
    id: UUID
    email: EmailStr
    first_name: str | None = None
    timezone: str | None = None
    avatar_url: HttpUrl | str | None = None
    marketing_emails: bool = False
    service_emails: bool = True
    created_at: datetime
    updated_at: datetime | None = None
    permissions: list[str] = Field(default_factory=list)


class NotificationPrefsRequest(BaseModel):
    """Тумблеры писем. Непереданное поле = не трогать это согласие.

    `service_emails` шире, чем «сервисные письма»: выключение — это глобальная отписка,
    она гасит и рекламу тоже.
    """

    marketing_emails: Annotated[bool | None, Field(None)] = None
    service_emails: Annotated[bool | None, Field(None)] = None

    @model_validator(mode="after")
    def _ensure_payload(self) -> "NotificationPrefsRequest":
        if not self.model_fields_set:
            raise ValueError("At least one preference must be provided")
        return self


class ProfileUpdateRequest(BaseModel):
    first_name: Annotated[str | None, Field(None, min_length=1, max_length=50)] = None
    timezone: Annotated[str | None, Field(None, min_length=1, max_length=50)] = None
    avatar_url: Annotated[str | None, Field(None, max_length=1000)] = None

    @model_validator(mode="after")
    def _ensure_payload(self) -> "ProfileUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for update")
        return self
