import logging
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from sqlalchemy.exc import IntegrityError, MultipleResultsFound, NoResultFound, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from service.infrastructure.database.postgresql import PgConnector
from service.shared.repositories.exceptions import (
    RepositoryError,
    RepositoryIntegrityError,
    RepositoryMultipleResultsError,
    RepositoryNotFoundError,
    RepositoryOperationalError,
)

logger = logging.getLogger(__name__)


P = ParamSpec("P")
R = TypeVar("R")


def require_session(session: AsyncSession | None) -> AsyncSession:
    """Narrow the optional session injected by ``@connection`` to a concrete one.

    Repository methods declare ``session: AsyncSession | None = None`` so callers
    may omit it, but the ``@connection`` decorator always supplies it at runtime.
    This raises explicitly (unlike ``assert``, which is stripped under ``python -O``)
    if the session is somehow missing.
    """
    if session is None:
        raise RepositoryError("DB session is required but was not provided")
    return session


async def _dispatch(func: Any, args: Any, kwargs: Any, *, session: AsyncSession | None) -> Any:
    """Выполнить репозиторный метод с маппингом ошибок SQLAlchemy → RepositoryError.

    commit/rollback — ТОЛЬКО когда сессию открыл сам декоратор (``session is not None``).
    Если сессию передал вызывающий, транзакцией владеет он: не коммитим и не откатываем её.
    Маппинг типов ошибок применяем в обоих случаях — это контракт репозитория, ортогональный
    владению транзакцией.
    """
    try:
        result = await func(*args, **kwargs)
        if session is not None:
            await session.commit()
        return result
    except IntegrityError as exc:
        if session is not None:
            await session.rollback()
        logger.exception("Data integrity violation")
        raise RepositoryIntegrityError("Uniqueness violation") from exc
    except NoResultFound as exc:
        if session is not None:
            await session.rollback()
        logger.warning("Record not found: %s", exc)
        raise RepositoryNotFoundError("Record not found") from exc
    except MultipleResultsFound as exc:
        if session is not None:
            await session.rollback()
        logger.exception("Multiple records found")
        raise RepositoryMultipleResultsError() from exc
    except OperationalError as exc:
        if session is not None:
            await session.rollback()
        logger.exception("Database connection error")
        raise RepositoryOperationalError("Database unavailable") from exc
    except Exception as exc:
        if session is not None:
            await session.rollback()
        logger.exception("Unexpected error occurred")
        raise RepositoryError("Internal repository error") from exc


def connection() -> Callable[
    [Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]
]:
    def decorator(
        func: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            self_instance = args[0]
            if not hasattr(self_instance, "connector"):
                raise AttributeError("Instance must have 'connector' attribute")

            # Вызывающий передал сессию → он владеет транзакцией. Не открываем свою
            # throwaway-сессию и не коммитим/откатываем чужую. Раньше декоратор ВСЕГДА
            # открывал свою сессию и коммитил ЕЁ — а запись, сделанная в переданную сессию,
            # не фиксировалась (терялась), плюс зря чекаутился второй коннект. Это уже
            # роняло реальный баг (FAILURE джоба терялся, job навис в PROCESSING).
            if kwargs.get("session") is not None:
                return await _dispatch(func, args, kwargs, session=None)

            connector: PgConnector = self_instance.connector
            async with connector.get_session_context() as session:
                kwargs["session"] = session
                return await _dispatch(func, args, kwargs, session=session)

        return wrapper

    return decorator
