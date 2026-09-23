import logging
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException, status

from service.models.db.db_models import UserSession
from service.models.key_value import SessionStatus, UserTypes
from service.models.profile_models import UserProfileLogic
from service.services.admin.application.runtime_settings import runtime_settings
from service.services.profile.application.dto import (
    CodeChallengeResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    ResendRequest,
    VerifyRequest,
)
from service.services.profile.application.email_codes import (
    codes_match,
    generate_numeric_code,
    hash_code,
)
from service.services.profile.application.ports.interfaces import (
    ProfileCachePort,
    VerificationCodeSenderPort,
)
from service.services.profile.application.profile_service import ProfileService
from service.services.profile.persistence.auth_repository import AuthRepository
from service.settings import AuthConfig, EmailConfig

logger = logging.getLogger(__name__)

# Namespace для хранения одноразового кода в Redis (RedisCacheService).
OTP_NAMESPACE = "auth:otp"


class AuthService:
    def __init__(
        self,
        config: AuthConfig,
        repository: AuthRepository,
        profile_source: ProfileService,
        email_config: EmailConfig,
        cache: ProfileCachePort | None = None,
        code_sender: VerificationCodeSenderPort | None = None,
    ) -> None:
        self.config = config
        self.repository = repository
        self.profile_source = profile_source
        self.email_config = email_config
        self.cache = cache
        self.code_sender = code_sender

    # ------------------------------------------------------------------ #
    # Регистрация: создаём аккаунт (email_verified=false) и шлём код.
    # ------------------------------------------------------------------ #
    async def register_user(
        self, user_agent: str, request_body: RegisterRequest
    ) -> CodeChallengeResponse:
        """Register new user with email and password. Sends a confirmation code."""

        normalized_email = self._normalize_email(request_body.email)

        # Basic password strength policy: >=8 chars, contains letter and digit
        pwd = request_body.password or ""
        if len(pwd) < 8 or not any(c.isalpha() for c in pwd) or not any(c.isdigit() for c in pwd):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "weak_password",
                    "message": "Password must be 8+ chars with a letter and a digit",
                },
            )

        # Раздельные согласия обязательны (152-ФЗ, с 01.09.2025). Фронт гейтит сабмит,
        # но бэкенд — источник истины: без обоих согласий регистрация невозможна.
        if not (request_body.consent_pd and request_body.consent_transfer):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "consent_required",
                    "message": "Both processing and transfer consents are required",
                },
            )

        existing_user = await self.profile_source.fetch_user_profile_by_email(normalized_email)
        if existing_user and getattr(existing_user, "email_verified", False):
            logger.warning("Registration rejected: user already exists")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "email_already_exists",
                    "message": "User with this email already exists",
                },
            )

        if existing_user:
            # Аккаунт есть, но не подтверждён → перерегистрация: обновляем пароль и
            # шлём новый код. Защищает реального владельца от «сквоттинга» его почты.
            await self.profile_source.update_password(
                existing_user.id, existing_user.email, request_body.password
            )
            await self.profile_source.record_consent(
                existing_user.id, existing_user.email, request_body.consent_version
            )
            logger.info("Re-registering unverified user")
        else:
            await self.profile_source.create_new_user(
                email=normalized_email,
                password=request_body.password,
                consent_version=request_body.consent_version,
                consent_marketing=bool(request_body.consent_marketing),
            )
            logger.info("Created new unverified user")

        await self._issue_code(normalized_email, purpose="register")
        return CodeChallengeResponse(email=normalized_email)

    # ------------------------------------------------------------------ #
    # Вход: проверяем пароль, затем шлём OTP (сессия — только после verify).
    # ------------------------------------------------------------------ #
    async def login(self, user_agent: str, request_body: LoginRequest) -> CodeChallengeResponse:
        """Verify password and send a one-time login code (OTP)."""

        normalized_email = self._normalize_email(request_body.email)

        user = await self.profile_source.fetch_user_profile_by_email(normalized_email)
        if not user or not self.profile_source.verify_password(
            request_body.password, user.password_hash
        ):
            logger.warning("Login rejected: invalid credentials")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_credentials", "message": "Invalid email or password"},
            )

        if not getattr(user, "is_active", True):
            logger.warning("Login rejected: inactive account")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "account_blocked", "message": "Account is blocked"},
            )

        # Код шлём ТОЛЬКО после верного пароля (нельзя рассылать коды кому попало).
        await self._issue_code(normalized_email, purpose="login")
        return CodeChallengeResponse(email=normalized_email)

    # ------------------------------------------------------------------ #
    # Проверка кода: помечаем email подтверждённым и выдаём сессию.
    # ------------------------------------------------------------------ #
    async def verify_code(self, user_agent: str, request_body: VerifyRequest) -> LoginResponse:
        """Verify the code, mark email as verified, and create a session."""

        self._require_verification_ready()
        normalized_email = self._normalize_email(request_body.email)

        stored = await self.cache.get_json(OTP_NAMESPACE, normalized_email)
        if not stored:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "code_expired",
                    "message": "The code has expired. Request a new one.",
                },
            )

        code = (request_body.code or "").strip()
        if not codes_match(code, self.config.secret, stored.get("code_hash", "")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_code", "message": "Invalid confirmation code"},
            )

        # Код одноразовый — гасим сразу после успешной сверки.
        await self.cache.invalidate(OTP_NAMESPACE, normalized_email)

        user = await self.profile_source.fetch_user_profile_by_email(normalized_email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_credentials", "message": "Invalid email or password"},
            )

        if not getattr(user, "is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "account_blocked", "message": "Account is blocked"},
            )

        if not getattr(user, "email_verified", False):
            await self.profile_source.mark_email_verified(user.id, user.email)

        session = await self._create_activated_session(
            user=user, user_agent=user_agent, fingerprint=None
        )
        logger.info("Email verified and session activated")
        return LoginResponse(jwt=session.token)  # type: ignore[arg-type]

    # ------------------------------------------------------------------ #
    # Повторная отправка кода (обобщённый ответ — не палим наличие адреса).
    # ------------------------------------------------------------------ #
    async def resend_code(
        self, user_agent: str, request_body: ResendRequest
    ) -> CodeChallengeResponse:
        normalized_email = self._normalize_email(request_body.email)
        user = await self.profile_source.fetch_user_profile_by_email(normalized_email)
        if user:
            purpose = "register" if not getattr(user, "email_verified", False) else "login"
            await self._issue_code(normalized_email, purpose=purpose)
        return CodeChallengeResponse(email=normalized_email)

    # ------------------------------------------------------------------ #
    # OTP helpers
    # ------------------------------------------------------------------ #
    def _require_verification_ready(self) -> None:
        """Фича требует Redis (хранилище кода) и отправителя — иначе 503."""
        if self.cache is None or self.code_sender is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "verification_unavailable",
                    "message": "Email verification is temporarily unavailable",
                },
            )

    def _code_ttl_seconds(self) -> int:
        return int(
            runtime_settings.get("email.code_ttl_seconds", self.email_config.code_ttl_seconds)
        )

    def _code_length(self) -> int:
        return int(runtime_settings.get("email.code_length", self.email_config.code_length))

    async def _issue_code(self, email: str, purpose: str) -> None:
        """Сгенерировать код, сохранить его хеш в Redis (TTL) и отправить письмо."""
        self._require_verification_ready()
        code = generate_numeric_code(self._code_length())
        payload = {"code_hash": hash_code(code, self.config.secret), "purpose": purpose}
        await self.cache.set_json(
            OTP_NAMESPACE, email, payload, ttl_seconds=self._code_ttl_seconds()
        )
        await self.code_sender.send(email=email, code=code, purpose=purpose)

    # ------------------------------------------------------------------ #
    # Session / JWT (без изменений)
    # ------------------------------------------------------------------ #
    async def _create_activated_session(
        self,
        user: UserProfileLogic,
        user_agent: str,
        fingerprint: str | None,
    ) -> UserSession:
        """Create an immediately activated session"""

        jwt_token = self._create_jwt(user.id, fingerprint, UserTypes.REGISTERED)

        new_session = UserSession(
            user_id=user.id,
            user_agent=user_agent,
            fingerprint=fingerprint,
            status=SessionStatus.ACTIVATED,
            session_code="",  # OTP хранится в Redis, не в сессии
            token=jwt_token,
            expires_at=datetime.now(UTC) + timedelta(hours=self.config.jwt_exp_hours),
        )
        return await self.repository.create_session(new_session)

    def _create_jwt(self, user_id, fingerprint: str | None, user_type: UserTypes) -> str:
        """Create JWT token for authenticated user"""

        payload = {
            "sub": str(user_id),
            "fingerprint": fingerprint,
            "type": user_type.value,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=self.config.jwt_exp_hours),
        }
        token = jwt.encode(payload, self.config.secret, algorithm=self.config.algorithm)
        return token

    def _normalize_email(self, email: str) -> str:
        """Normalize email address"""
        local_part, domain_part = email.rsplit("@", 1)

        if "+" in local_part:
            local_part = local_part.split("+")[0]

        return f"{local_part}@{domain_part}".lower()
