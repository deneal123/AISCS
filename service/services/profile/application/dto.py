from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class GetProfileOverviewQuery(BaseModel):
    user_id: UUID


class UpdateProfileCommand(BaseModel):
    user_id: UUID
    first_name: str | None = None
    timezone: str | None = None
    avatar_url: str | None = None


class UpdateNotificationPrefsCommand(BaseModel):
    """Почтовые предпочтения. `None` = поле не пришло → это согласие не трогаем."""

    user_id: UUID
    marketing: bool | None = None
    service: bool | None = None


class DeleteChatHistoryCommand(BaseModel):
    user_id: UUID


class ProfileOverviewResult(BaseModel):
    id: UUID
    email: str
    first_name: str | None
    timezone: str | None
    avatar_url: str | None
    # Наружу — булевы: API говорит «письма включены», БД хранит «когда согласие дано».
    marketing_emails: bool = False
    service_emails: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EmailField(BaseModel):
    email: Annotated[EmailStr, Field(..., description="User email", min_length=5, max_length=500)]


class RegisterRequest(EmailField):
    password: Annotated[
        str,
        Field(..., min_length=8, max_length=100, description="User password"),
    ]
    fingerprint: Annotated[
        str | None,
        Field(None, min_length=10, max_length=1000, description="User device fingerprint"),
    ]
    # Раздельные согласия (152-ФЗ, с 01.09.2025): общее на обработку ПДн + отдельное
    # на передачу LLM-провайдерам/трансграничную. Оба обязательны (валидация в auth_service).
    consent_pd: Annotated[bool, Field(False, description="Consent to personal-data processing")]
    consent_transfer: Annotated[
        bool, Field(False, description="Separate consent to LLM/cross-border transfer")
    ]
    consent_version: Annotated[
        str | None,
        Field(None, max_length=50, description="Version of legal documents accepted"),
    ]
    # Маркетинг — ОТДЕЛЬНОЕ и ДОБРОВОЛЬНОЕ согласие: ФЗ «О рекламе», ст. 18. Согласие на
    # обработку ПДн рекламу не покрывает, поэтому галочка своя и по умолчанию снята.
    # Обязательной её делать нельзя — иначе это уже не согласие.
    consent_marketing: Annotated[
        bool, Field(False, description="Optional consent to marketing emails")
    ]


class RegisterResponse(EmailField):
    user_id: Annotated[UUID, Field(..., description="User ID")]


class LoginRequest(EmailField):
    password: Annotated[str, Field(..., description="User password", min_length=4, max_length=100)]


class LoginResponse(BaseModel):
    jwt: Annotated[str, Field(..., description="JWT token with user profile")]


class VerifyRequest(EmailField):
    code: Annotated[
        str, Field(..., min_length=4, max_length=12, description="Email verification code")
    ]


class ResendRequest(EmailField):
    pass


class CodeChallengeResponse(BaseModel):
    """Ответ на register/login/resend: код отправлен на почту, ждём verify."""

    status: Annotated[str, Field(default="code_sent", description="Challenge status")] = "code_sent"
    email: Annotated[str, Field(..., description="Email the code was sent to")]
