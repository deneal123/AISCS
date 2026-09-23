import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from service.models.db.db_models import UserFile
from service.models.key_value import ServiceType
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

logger = logging.getLogger(__name__)


class FileRepository(BaseRepository):
    @connection()
    async def fetch_user_files_metadata(
        self,
        user_id: UUID,
        mode: ServiceType,
        session: AsyncSession | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
        before: tuple[datetime, UUID] | None = None,
    ) -> list[UserFile]:
        session = require_session(session)
        query = select(UserFile).where(UserFile.user_id == user_id, UserFile.type == mode)
        if before is not None:
            created_at, file_id = before
            query = query.where(
                or_(
                    UserFile.created_at < created_at,
                    and_(UserFile.created_at == created_at, UserFile.id < file_id),
                    UserFile.created_at.is_(None),
                )
            )
        query = query.order_by(UserFile.created_at.desc().nullslast(), UserFile.id.desc())
        if before is None:
            query = query.offset(max(0, int(offset)))
        if limit is not None:
            query = query.limit(max(1, int(limit)))
        result = await session.execute(query)
        return list(result.scalars().all())

    @connection()
    async def fetch_user_file_by_id(
        self, user_id: UUID, file_id: UUID, session: AsyncSession | None = None
    ) -> UserFile | None:
        session = require_session(session)
        result = await session.execute(
            select(UserFile).where(UserFile.user_id == user_id, UserFile.id == file_id)
        )
        return result.scalar_one_or_none()

    @connection()
    async def fetch_user_file_by_upload_intent(
        self,
        user_id: UUID,
        upload_intent_id: UUID,
        session: AsyncSession | None = None,
    ) -> UserFile | None:
        session = require_session(session)
        result = await session.execute(
            select(UserFile).where(
                UserFile.user_id == user_id,
                UserFile.upload_intent_id == upload_intent_id,
            )
        )
        return result.scalar_one_or_none()

    @connection()
    async def fetch_user_file_by_name(
        self, user_id: UUID, file_name: str, session: AsyncSession | None = None
    ) -> UserFile | None:
        session = require_session(session)
        result = await session.execute(
            select(UserFile).where(UserFile.user_id == user_id, UserFile.file_name == file_name)
        )
        return result.scalar_one_or_none()

    @connection()
    async def add_file_metadata(
        self, file_metadata: UserFile, session: AsyncSession | None = None
    ) -> UserFile:
        session = require_session(session)
        logger.debug("adding file metadata", extra={"component": "file_repository"})
        session.add(file_metadata)
        await session.flush()
        logger.debug("file metadata added", extra={"component": "file_repository"})
        return file_metadata

    @connection()
    async def delete_file_metadata(
        self, user_id: UUID, file_id: UUID, session: AsyncSession | None = None
    ) -> None:
        session = require_session(session)
        logger.debug("deleting file metadata", extra={"component": "file_repository"})
        await session.execute(
            delete(UserFile).where(UserFile.user_id == user_id, UserFile.id == file_id)
        )

    @connection()
    async def delete_file_metadata_by_name(
        self, user_id: UUID, file_name: str, session: AsyncSession | None = None
    ) -> None:
        session = require_session(session)
        logger.debug("deleting file metadata", extra={"component": "file_repository"})
        await session.execute(
            delete(UserFile).where(UserFile.user_id == user_id, UserFile.file_name == file_name)
        )
