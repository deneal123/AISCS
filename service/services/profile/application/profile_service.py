import logging
from uuid import UUID

from argon2 import PasswordHasher

from service.models.profile_models import UserProfileLogic
from service.services.profile.application.dto import (
    DeleteChatHistoryCommand,
    GetProfileOverviewQuery,
    ProfileOverviewResult,
    UpdateNotificationPrefsCommand,
    UpdateProfileCommand,
)
from service.services.profile.application.mappers import to_profile_overview_result
from service.services.profile.application.ports.interfaces import (
    ProfileCachePort,
    ProfileRepositoryPort,
)
from service.settings import ProfileConfig

logger = logging.getLogger(__name__)

# v2 — в кэшируемый профиль добавлены согласия на письма. Старые записи этих полей не
# содержат, и Pydantic подставил бы им None, то есть «согласия нет» — до 15 минут (TTL)
# профиль показывал бы чужую правду о согласии. Смена неймспейса разом обесценивает их.
PROFILE_BY_ID_NAMESPACE = "profile:id:v2"
PROFILE_BY_EMAIL_NAMESPACE = "profile:email:v2"
PROFILE_MUTABLE_FIELDS = {"first_name", "timezone", "avatar_url"}


class ProfileService:
    def __init__(
        self,
        config: ProfileConfig,
        repository: ProfileRepositoryPort,
        cache: ProfileCachePort | None = None,
        cache_ttl_seconds: int | None = None,
    ) -> None:
        self.config = config
        self.repository = repository
        self.ph = PasswordHasher()
        self.cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds

    async def _cache_profile(self, profile: UserProfileLogic) -> None:
        if not self.cache:
            return
        payload = profile.model_dump()
        await self.cache.set_json(
            PROFILE_BY_ID_NAMESPACE,
            str(profile.id),
            payload,
            ttl_seconds=self._cache_ttl_seconds,
        )
        await self.cache.set_json(
            PROFILE_BY_EMAIL_NAMESPACE,
            profile.email.lower(),
            payload,
            ttl_seconds=self._cache_ttl_seconds,
        )

    async def _get_cached_profile_by_id(self, user_id: UUID) -> UserProfileLogic | None:
        if not self.cache:
            return None
        cached = await self.cache.get_json(PROFILE_BY_ID_NAMESPACE, str(user_id))
        if not cached:
            return None
        try:
            return UserProfileLogic.model_validate(cached)
        except Exception:  # noqa: BLE001
            logger.warning("Invalid cached profile by id; purging")
            await self.cache.invalidate(PROFILE_BY_ID_NAMESPACE, str(user_id))
            return None

    async def _get_cached_profile_by_email(self, email: str) -> UserProfileLogic | None:
        if not self.cache:
            return None
        cache_key = email.lower()
        cached = await self.cache.get_json(PROFILE_BY_EMAIL_NAMESPACE, cache_key)
        if not cached:
            return None
        try:
            return UserProfileLogic.model_validate(cached)
        except Exception:  # noqa: BLE001
            logger.warning("Invalid cached profile by email; purging")
            await self.cache.invalidate(PROFILE_BY_EMAIL_NAMESPACE, cache_key)
            return None

    async def _invalidate_profile_cache(self, user_id: UUID, email: str) -> None:
        if not self.cache:
            return
        await self.cache.invalidate(PROFILE_BY_ID_NAMESPACE, str(user_id))
        await self.cache.invalidate(PROFILE_BY_EMAIL_NAMESPACE, email.lower())

    async def _refresh_profile_cache(
        self, profile: UserProfileLogic, previous_email: str | None = None
    ) -> None:
        if not self.cache:
            return
        if previous_email and previous_email.lower() != profile.email.lower():
            await self.cache.invalidate(PROFILE_BY_EMAIL_NAMESPACE, previous_email.lower())
        await self._cache_profile(profile)

    async def fetch_user_profile(self, user_id: UUID) -> UserProfileLogic:
        logger.info("Fetching user profile by id")

        cached_profile = await self._get_cached_profile_by_id(user_id)
        if cached_profile:
            logger.debug("User profile cache hit by id")
            return cached_profile

        user_profile = await self.repository.fetch_user_profile(str(user_id))
        if not user_profile:
            logger.error("User profile not found by id")
            raise ValueError("User profile not found")
        logger.debug("User profile fetched by id")

        await self._cache_profile(user_profile)

        return user_profile

    async def get_profile_overview(self, query: GetProfileOverviewQuery) -> ProfileOverviewResult:
        profile = await self.fetch_user_profile(query.user_id)
        return to_profile_overview_result(profile)

    async def fetch_user_profile_by_email(self, email: str) -> UserProfileLogic | None:
        logger.info("Fetching user profile by email")

        cached_profile = await self._get_cached_profile_by_email(email)
        if cached_profile:
            logger.debug("User profile cache hit by email")
            return cached_profile

        user_profile = await self.repository.fetch_user_by_email(email)
        if user_profile:
            logger.debug("User profile fetched by email")
            await self._cache_profile(user_profile)
        else:
            logger.debug("User profile not found by email")

        return user_profile

    async def create_new_user(
        self,
        email: str,
        password: str,
        consent_version: str | None = None,
        consent_marketing: bool = False,
    ) -> UserProfileLogic:
        logger.info("Creating new user")
        password_hash = self.ph.hash(password)
        new_user = await self.repository.create_user(
            email=email,
            password_hash=password_hash,
            consent_version=consent_version,
            consent_marketing=consent_marketing,
        )
        await self._cache_profile(new_user)
        return new_user

    def verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against hash"""
        try:
            return self.ph.verify(password_hash, password)
        except Exception:
            return False

    async def mark_email_verified(self, user_id: UUID, email: str) -> None:
        """Пометить email подтверждённым (после успешного ввода кода)."""
        await self.repository.set_email_verified(str(user_id))
        await self._invalidate_profile_cache(user_id, email)

    async def update_password(self, user_id: UUID, email: str, password: str) -> None:
        """Сменить пароль (перерегистрация неподтверждённого аккаунта)."""
        password_hash = self.ph.hash(password)
        await self.repository.update_password_hash(str(user_id), password_hash)
        await self._invalidate_profile_cache(user_id, email)

    async def record_consent(self, user_id: UUID, email: str, consent_version: str | None) -> None:
        """Зафиксировать раздельные согласия (перерегистрация неподтверждённого аккаунта)."""
        await self.repository.record_consent(str(user_id), consent_version)
        await self._invalidate_profile_cache(user_id, email)

    async def update_profile_details(self, command: UpdateProfileCommand) -> ProfileOverviewResult:
        updates = command.model_dump(exclude={"user_id"}, exclude_unset=True)
        logger.info(
            "Updating profile for user_id=%s with fields=%s", command.user_id, list(updates.keys())
        )

        fields_to_apply = {k: v for k, v in updates.items() if k in PROFILE_MUTABLE_FIELDS}
        if not fields_to_apply:
            current = await self.fetch_user_profile(command.user_id)
            return to_profile_overview_result(current)

        profile = await self.fetch_user_profile(command.user_id)
        previous_email = profile.email

        for field_name, value in fields_to_apply.items():
            setattr(profile, field_name, value)

        updated_profile = await self.repository.update_user_profile(profile)
        await self._refresh_profile_cache(updated_profile, previous_email)

        logger.info("Profile updated for user_id=%s", command.user_id)
        return to_profile_overview_result(updated_profile)

    @staticmethod
    def _resolve_email_prefs(
        marketing: bool | None, service: bool | None
    ) -> tuple[bool | None, bool | None]:
        """Выключение всех писем гасит и рекламу — это отзыв согласия, а не пауза.

        Без этого правила согласие оставалось бы «спящим»: человек выключил письма, потом
        вернул себе сервисные — и вместе с ними внезапно снова получил рекламу, которую
        отозвал. Правило живёт здесь, в одном месте, чтобы отписка по ссылке из письма и
        тумблер в профиле не разъехались.
        """
        if service is False:
            return False, False
        return marketing, service

    async def update_email_preferences(
        self, command: UpdateNotificationPrefsCommand
    ) -> ProfileOverviewResult:
        """Включить/выключить письма. `None` в поле = не трогать это согласие."""
        profile = await self.fetch_user_profile(command.user_id)
        marketing, service = self._resolve_email_prefs(command.marketing, command.service)
        updated = await self.repository.update_email_preferences(
            str(command.user_id), marketing=marketing, service=service
        )
        await self._refresh_profile_cache(updated, profile.email)
        return to_profile_overview_result(updated)

    async def unsubscribe_all(self, user_id: UUID) -> bool:
        """Отписка по ссылке из письма. → True, если состояние изменилось.

        Гасит и рекламу тоже: отзыв согласия — это отзыв, а не пауза. Оставь мы
        `marketing_consent_at`, человек, вернувший себе сервисные письма в профиле,
        внезапно получил бы вместе с ними и рекламу, которую отозвал.

        Идёт через сервис, а не UPDATE в обход: профиль лежит в Redis на 15 минут, и
        сырой UPDATE оставил бы в кэше «письма включены» сразу после отписки.
        """
        profile = await self.fetch_user_profile(user_id)
        if profile.unsubscribed_at is not None and profile.marketing_consent_at is None:
            return False
        updated = await self.repository.update_email_preferences(
            str(user_id), marketing=False, service=False
        )
        await self._refresh_profile_cache(updated, profile.email)
        return True

    async def delete_chat_history(self, command: DeleteChatHistoryCommand) -> None:
        cached = await self._get_cached_profile_by_id(command.user_id)
        await self.repository.delete_user_chat_history(str(command.user_id))
        if cached:
            await self._invalidate_profile_cache(command.user_id, cached.email)
        logger.info("Deleted chat history for user")
