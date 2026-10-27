import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from service.settings import PgConfig

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# PgConnector принимает PgConfig (из composition): у него есть рабочий .dsn и
# .settings (внутренняя Postgresql-модель с параметрами пула). Сам Postgresql сюда
# напрямую не передаётся (у него нет ни рабочего .dsn, ни .settings).
_PgConfigT = PgConfig


class PgConnector:
    _engine: AsyncEngine | None = None
    _session_maker: async_sessionmaker | None = None
    _bound_loop: asyncio.AbstractEventLoop | None = None

    def __init__(self, config: _PgConfigT, force_new: bool = False) -> None:
        self.config = config
        self._force_new = force_new
        self._engine = self._get_engine()
        self._session_maker = self._get_session_maker()

    def _get_engine(self) -> AsyncEngine:
        if self._force_new:
            return create_async_engine(
                self.config.dsn,
                echo=self.config.settings.db_echo,
                echo_pool=self.config.settings.db_echo,
                pool_size=self.config.settings.db_pool_size,
                max_overflow=self.config.settings.db_max_overflow,
                pool_timeout=self.config.settings.db_pool_timeout,
                pool_recycle=self.config.settings.db_pool_recycle,
                pool_pre_ping=self.config.settings.db_pool_pre_ping,
                future=True,
            )

        try:
            current_loop = asyncio.get_event_loop()
        except RuntimeError:
            current_loop = None

        if PgConnector._engine is not None and PgConnector._bound_loop != current_loop:
            logger.info("Event loop changed, recreating database engine")
            old_engine = PgConnector._engine
            PgConnector._engine = None
            PgConnector._session_maker = None
            try:
                # Восстановительный путь для пула, оставленного чужим/закрытым loop.
                # Штатный chat-worker закрывает свой пул до завершения loop.
                # ВАЖНО: close=False — иначе SQLAlchemy пытается ЗАКРЫТЬ
                # каждый asyncpg-коннект синхронно (`await_only` внутри), а его loop мёртв →
                # `MissingGreenlet: greenlet_spawn has not been called` сыпется ERROR'ом на
                # КАЖДЫЙ коннект, и закрытие всё равно не удаётся. close=False сбрасывает
                # пул без этих обречённых закрытий; осиротевшие коннекты (их loop мёртв, они
                # и так нерабочие) добирает GC/таймаут Postgres. Это не замена штатной очистке.
                old_engine.sync_engine.dispose(close=False)
            except Exception:
                logger.warning(
                    "database pool retirement failed",
                    extra={"component": "database", "failure_code": "cleanup"},
                )

        if not PgConnector._engine:
            PgConnector._engine = create_async_engine(
                self.config.dsn,
                echo=self.config.settings.db_echo,
                echo_pool=self.config.settings.db_echo,
                pool_size=self.config.settings.db_pool_size,
                max_overflow=self.config.settings.db_max_overflow,
                pool_timeout=self.config.settings.db_pool_timeout,
                pool_recycle=self.config.settings.db_pool_recycle,
                pool_pre_ping=self.config.settings.db_pool_pre_ping,
                future=True,
            )
            PgConnector._bound_loop = current_loop
        return PgConnector._engine

    def _get_session_maker(self) -> async_sessionmaker:
        if self._force_new:
            return async_sessionmaker(
                bind=self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
        if not PgConnector._session_maker:
            PgConnector._session_maker = async_sessionmaker(
                bind=self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
        return PgConnector._session_maker

    async def get_session(self) -> AsyncGenerator[AsyncSession]:
        """Get database session for use as FastAPI dependency"""
        if self._session_maker is None:
            logger.error("Attempted to get session but sessionmaker is not initialized")
            raise ValueError("PostgreSQL sessionmaker is not initialized")

        logger.debug("Creating new database session")
        try:
            async with self._session_maker() as session:
                logger.debug("Database session created successfully")
                yield session
                logger.debug("Database session closed successfully")
        except Exception:
            logger.warning(
                "database session failed",
                extra={"component": "database", "failure_code": "internal"},
            )
            raise

    def get_session_context(self) -> AsyncSession:
        """Returns context manager for use outside FastAPI dependency injection."""
        if self._session_maker is None:
            logger.error("Attempted to get session context but sessionmaker is not initialized")
            raise ValueError("PostgreSQL sessionmaker is not initialized")

        logger.debug("Creating database session context")
        return self._session_maker()

    async def verify_connection(self) -> None:
        """Open a short session and execute a trivial statement to verify connectivity."""
        if self._engine is None:
            raise ValueError("PostgreSQL engine is not initialized")
        try:
            async with self.get_session_context() as session:
                await session.execute(text("SELECT 1"))
                await session.commit()
            logger.debug("PostgreSQL connection verified successfully")
        except Exception:
            logger.warning(
                "database verification failed",
                extra={"component": "database", "failure_code": "unavailable"},
            )
            raise

    async def close(self) -> None:
        """Dispose engine connections gracefully."""
        await self._dispose_engine(self._engine)

    @classmethod
    async def close_current_loop(cls) -> None:
        """Закрыть только общий пул текущего worker-loop, не затрагивая чужой."""
        if cls._bound_loop is not None and cls._bound_loop is not asyncio.get_running_loop():
            return
        await cls._dispose_engine(cls._engine)

    @classmethod
    async def _dispose_engine(cls, engine: AsyncEngine | None) -> None:
        if engine is None:
            return
        try:
            await engine.dispose()
            # Не сбрасываем новый пул, если владение изменилось за время await.
            if cls._engine is engine:
                cls._engine = None
                cls._session_maker = None
                cls._bound_loop = None
            logger.debug("PostgreSQL engine disposed")
        except Exception:
            logger.warning(
                "database cleanup failed",
                extra={"component": "database", "failure_code": "cleanup"},
            )
