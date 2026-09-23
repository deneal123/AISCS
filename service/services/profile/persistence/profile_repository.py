import logging
from datetime import UTC, datetime

from sqlalchemy import case, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from service.models.db.db_models import User
from service.models.profile_models import UserProfileLogic
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session
from service.shared.repositories.exceptions import RepositoryNotFoundError

logger = logging.getLogger(__name__)


class ProfileRepository(BaseRepository):
    @connection()
    async def create_user(
        self,
        email: str,
        password_hash: str,
        consent_version: str | None = None,
        consent_marketing: bool = False,
        session: AsyncSession | None = None,
    ) -> UserProfileLogic:
        session = require_session(session)

        # Регистрация требует ОБОИХ раздельных согласий (валидируется в auth_service),
        # поэтому при наличии версии фиксируем обе метки времени.
        now = datetime.now(UTC) if consent_version else None
        # Маркетинг — ДОБРОВОЛЬНОЕ и отдельное согласие (ФЗ «О рекламе», ст. 18):
        # метку ставим только если галочка реально стояла.
        new_user = User(
            email=email,
            password_hash=password_hash,
            available_launches=10,
            consent_pd_at=now,
            consent_transfer_at=now,
            consent_version=consent_version,
            marketing_consent_at=now if consent_marketing else None,
        )
        logger.debug("Creating user entity")
        session.add(new_user)
        await session.flush()
        logger.debug("User entity created")

        return UserProfileLogic.model_validate(new_user)

    @connection()
    async def fetch_user_profile(
        self, user_id: str, session: AsyncSession | None = None
    ) -> UserProfileLogic | None:
        session = require_session(session)
        logger.debug("Fetching user profile by id")

        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        db_user = result.scalar_one_or_none()

        if db_user:
            profile = UserProfileLogic.model_validate(db_user)
            logger.debug("User profile fetched by id")
            return profile
        logger.debug("User profile not found by id")
        return None

    @connection()
    async def fetch_user_by_email(
        self, email: str, session: AsyncSession | None = None
    ) -> UserProfileLogic | None:
        session = require_session(session)
        logger.debug("Fetching user profile by email")

        stmt = select(User).where(User.email == email)
        result = await session.execute(stmt)
        db_user = result.scalar_one_or_none()

        if db_user:
            profile = UserProfileLogic.model_validate(db_user)
            logger.debug("User profile fetched by email")
            return profile
        logger.debug("User profile not found by email")
        return None

    @connection()
    async def update_user_profile(
        self, user: UserProfileLogic, session: AsyncSession | None = None
    ) -> UserProfileLogic:
        session = require_session(session)
        logger.debug("Updating user profile")

        payload = user.model_dump()
        update_values = {
            "email": payload["email"],
            "password_hash": payload["password_hash"],
            "first_name": payload.get("first_name"),
            "timezone": payload.get("timezone"),
            "avatar_url": payload.get("avatar_url"),
        }

        stmt = update(User).where(User.id == payload["id"]).values(**update_values).returning(User)
        result = await session.execute(stmt)
        db_user = result.scalar_one_or_none()

        if not db_user:
            raise RepositoryNotFoundError("User not found")

        updated_user = UserProfileLogic.model_validate(db_user)
        logger.debug("User profile updated")
        return updated_user

    @connection()
    async def set_email_verified(self, user_id: str, session: AsyncSession | None = None) -> None:
        session = require_session(session)
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(email_verified=True, verified_at=func.now())
        )

    @connection()
    async def update_password_hash(
        self, user_id: str, password_hash: str, session: AsyncSession | None = None
    ) -> None:
        session = require_session(session)
        await session.execute(
            update(User).where(User.id == user_id).values(password_hash=password_hash)
        )

    @connection()
    async def record_consent(
        self, user_id: str, consent_version: str | None, session: AsyncSession | None = None
    ) -> None:
        """Зафиксировать раздельные согласия (перерегистрация неподтверждённого аккаунта)."""
        session = require_session(session)
        now = datetime.now(UTC)
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                consent_pd_at=now,
                consent_transfer_at=now,
                consent_version=consent_version,
            )
        )

    @connection()
    async def update_email_preferences(
        self,
        user_id: str,
        marketing: bool | None = None,
        service: bool | None = None,
        session: AsyncSession | None = None,
    ) -> UserProfileLogic:
        """Почтовые предпочтения. `None` = не трогать это согласие.

        `marketing` — реклама (ФЗ «О рекламе», ст. 18); `service` — письма о состоянии
        аккаунта. Второе шире первого: `unsubscribed_at` гасит ВСЁ, включая рекламу.
        """
        session = require_session(session)
        values: dict[str, object] = {}

        # CASE, а не NOW() в лоб: повтор «включено → включено» не должен двигать метку.
        # Иначе идемпотентный запрос переписывал бы дату исходного согласия сегодняшней —
        # то есть подделывал бы юридическую запись о том, КОГДА согласие было дано.
        if marketing is not None:
            values["marketing_consent_at"] = (
                case(
                    (User.marketing_consent_at.is_(None), func.now()),
                    else_=User.marketing_consent_at,
                )
                if marketing
                else None
            )
        if service is not None:
            values["unsubscribed_at"] = (
                None
                if service
                else case(
                    (User.unsubscribed_at.is_(None), func.now()),
                    else_=User.unsubscribed_at,
                )
            )

        if not values:
            profile = await self.fetch_user_profile(user_id, session=session)
            if not profile:
                raise RepositoryNotFoundError("User not found")
            return profile

        stmt = update(User).where(User.id == user_id).values(**values).returning(User)
        result = await session.execute(stmt)
        db_user = result.scalar_one_or_none()
        if not db_user:
            raise RepositoryNotFoundError("User not found")

        logger.info("Email preferences updated")
        return UserProfileLogic.model_validate(db_user)

    @connection()
    async def delete_user_chat_history(
        self, user_id: str, session: AsyncSession | None = None
    ) -> None:
        session = require_session(session)
        await session.execute(
            text(
                "DELETE FROM profile.chat_messages WHERE thread_id IN (SELECT id "
                "FROM profile.chat_threads WHERE user_id = :uid)"
            ),
            {"uid": user_id},
        )
        await session.execute(
            text("DELETE FROM profile.chat_threads WHERE user_id = :uid"),
            {"uid": user_id},
        )
