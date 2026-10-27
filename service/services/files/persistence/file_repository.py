import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import String, and_, cast, delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from service.models.db.db_models import UserFile
from service.models.key_value import ServiceType
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

logger = logging.getLogger(__name__)


class FileRepository(BaseRepository):
    async def _lock_owned_file(self, session: AsyncSession, owner: UUID, file_id: UUID) -> None:
        # A transaction-scoped lock also protects a currently absent row. The
        # same session owns validation, mutation and commit; no extra pool slot.
        digest = hashlib.sha256(b"gpthub:owned-file:v1" + owner.bytes + file_id.bytes).digest()
        lock_id = int.from_bytes(digest[:8], "big", signed=True)
        async with asyncio.timeout(10):
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id}
            )

    @connection()
    async def add_direct_file_metadata(
        self,
        file_metadata: UserFile,
        verify_admission: Callable[[], Awaitable[bool]],
        session: AsyncSession | None = None,
    ) -> UserFile | None:
        session = require_session(session)
        await self._lock_owned_file(session, file_metadata.user_id, file_metadata.id)
        if not await verify_admission():
            return None
        return await self.add_file_metadata(file_metadata, session=session)

    @connection()
    async def delete_owned_file_atomically(
        self,
        user_id: UUID,
        file_id: UUID,
        before_delete: Callable[[UserFile], Awaitable[None]],
        session: AsyncSession | None = None,
    ) -> bool:
        session = require_session(session)
        await self._lock_owned_file(session, user_id, file_id)
        row = await self.fetch_user_file_by_id(user_id, file_id, session=session)
        if row is None:
            return False
        await before_delete(row)
        await self.delete_file_metadata(user_id, file_id, session=session)
        return True

    @connection()
    async def remove_unreferenced_pending(
        self,
        owner: UUID,
        file_id: UUID,
        key: str,
        remove: Callable[[], Awaitable[bool]],
        session: AsyncSession | None = None,
    ) -> bool:
        """Serialize with callback/DELETE, protecting even legacy references to source keys."""
        session = require_session(session)
        await self._lock_owned_file(session, owner, file_id)
        async with asyncio.timeout(10):
            referenced = await session.scalar(
                select(UserFile.id).where(UserFile.file_name == key).limit(1)
            )
        if referenced is not None:
            return False
        return await remove()

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
        search: str = "",
    ) -> list[UserFile]:
        session = require_session(session)
        query = select(UserFile).where(UserFile.user_id == user_id, UserFile.type == mode)
        if search:
            legacy_name = func.concat(
                "Ранее загруженный файл ",
                func.substr(cast(UserFile.id, String), 1, 8),
                func.lower(func.substring(UserFile.file_name, r"\.[a-zA-Z0-9]{1,12}$")),
            )
            display_name = func.coalesce(
                func.nullif(func.btrim(UserFile.original_name), ""), legacy_name
            )
            query = query.where(display_name.icontains(search, autoescape=True))
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
