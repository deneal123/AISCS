"""Контракт @connection при ЯВНО переданной сессии (аудит T2.2).

Ловушка: декоратор ВСЕГДА открывал свою сессию и коммитил ЕЁ (session_processor.py:57).
Когда вызывающий передавал `session=X`, func писал в X, а декоратор коммитил свою пустую
throwaway-сессию — запись в X не фиксировалась (её должен коммитить вызывающий), плюс
зря открывалась лишняя сессия/соединение. Это уже роняло реальный баг (FAILURE джоба
терялся, job навис в PROCESSING — обход ручными commit в воркере).

Контракт: сессию создал декоратор → он ей и владеет (commit/rollback). Сессию передал
вызывающий → владелец он; декоратор не открывает свою и не трогает транзакцию.
"""

import pytest

from service.shared.repositories.decorators.session_processor import connection, require_session


class _FakeSession:
    def __init__(self, name: str) -> None:
        self.name = name
        self.committed = 0
        self.rolled_back = 0

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


class _FakeCtx:
    def __init__(self, session: _FakeSession) -> None:
        self._s = session

    async def __aenter__(self) -> _FakeSession:
        return self._s

    async def __aexit__(self, *a) -> bool:
        return False


class _FakeConnector:
    def __init__(self) -> None:
        self.context_opens = 0
        self.last_session: _FakeSession | None = None

    def get_session_context(self) -> _FakeCtx:
        self.context_opens += 1
        self.last_session = _FakeSession("decorator")
        return _FakeCtx(self.last_session)


class _Repo:
    def __init__(self, connector: _FakeConnector) -> None:
        self._connector = connector

    @property
    def connector(self) -> _FakeConnector:
        return self._connector

    @connection()
    async def write(self, *, session=None) -> str:
        return require_session(session).name  # какую сессию использовал func?


@pytest.mark.asyncio
async def test_passed_session_not_shadowed_by_throwaway() -> None:
    """Переданная сессия: декоратор НЕ открывает свою и НЕ коммитит чужую."""
    conn = _FakeConnector()
    caller = _FakeSession("caller")
    used = await _Repo(conn).write(session=caller)

    assert used == "caller", "func должен работать с ПЕРЕДАННОЙ сессией"
    assert conn.context_opens == 0, "декоратор открыл лишнюю throwaway-сессию поверх переданной"
    assert caller.committed == 0, "коммит переданной сессии — забота вызывающего, не декоратора"


@pytest.mark.asyncio
async def test_decorator_owns_session_when_not_passed() -> None:
    """Без переданной сессии — декоратор открывает свою и коммитит ИМЕННО ЕЁ."""
    conn = _FakeConnector()
    used = await _Repo(conn).write()

    assert used == "decorator"
    assert conn.context_opens == 1
    assert conn.last_session.committed == 1, "декоратор обязан закоммитить созданную им сессию"


@pytest.mark.asyncio
async def test_passed_session_still_maps_repository_errors() -> None:
    """Маппинг типов ошибок (контракт репозитория) сохраняется и на переданной сессии."""
    from sqlalchemy.exc import NoResultFound

    from service.shared.repositories.exceptions import RepositoryNotFoundError

    class _Boom(_Repo):
        @connection()
        async def boom(self, *, session=None):
            require_session(session)
            raise NoResultFound("nope")

    with pytest.raises(RepositoryNotFoundError):
        await _Boom(_FakeConnector()).boom(session=_FakeSession("caller"))
