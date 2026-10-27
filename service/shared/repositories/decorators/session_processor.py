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


async def _rollback_owned(session: AsyncSession | None) -> None:
    """A failed rollback cannot prove a clean transaction or leak driver text.

    Only the decorator-owned session is eligible. Do not retry or convert a
    disconnect into integrity/not-found: callers need the uncertain persistence
    path, not a claim that the original failure was safely rolled back.
    """
    if session is None:
        return
    try:
        await session.rollback()
    except Exception:
        logger.warning(
            "repository rollback unavailable",
            extra={"component": "repository", "failure_code": "unavailable"},
        )
        raise RepositoryOperationalError("Database unavailable") from None


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
    except IntegrityError:
        await _rollback_owned(session)
        logger.warning(
            "repository operation failed",
            extra={"component": "repository", "failure_code": "integrity"},
        )
        raise RepositoryIntegrityError("Uniqueness violation") from None
    except NoResultFound:
        await _rollback_owned(session)
        logger.warning(
            "repository operation failed",
            extra={"component": "repository", "failure_code": "not_found"},
        )
        raise RepositoryNotFoundError("Record not found") from None
    except MultipleResultsFound:
        await _rollback_owned(session)
        logger.warning(
            "repository operation failed",
            extra={"component": "repository", "failure_code": "multiple_results"},
        )
        raise RepositoryMultipleResultsError() from None
    except OperationalError:
        await _rollback_owned(session)
        logger.warning(
            "repository operation failed",
            extra={"component": "repository", "failure_code": "unavailable"},
        )
        raise RepositoryOperationalError("Database unavailable") from None
    except Exception:
        await _rollback_owned(session)
        logger.warning(
            "repository operation failed",
            extra={"component": "repository", "failure_code": "internal"},
        )
        raise RepositoryError("Internal repository error") from None


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
