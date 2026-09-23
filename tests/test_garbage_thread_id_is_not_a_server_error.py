"""Мусор в пути — это «нет такого диалога», а не «сломался сервер».

🔴 НАЙДЕНО ЖИВЫМ ПРОГОНОМ. `chat_threads.thread_id` — колонка типа `uuid`, и строка вроде
`nope` для неё НЕПРЕДСТАВИМА: Postgres отвергает запрос ошибкой типа, драйвер поднимает её
наверх, наружу уезжает 500. Снаружи это выглядит как поломка платформы на любую опечатку в
адресе, а внутри — как поток `ERROR` в логах, среди которых настоящие сбои теряются.

⚠️ Правило живёт в РЕПОЗИТОРИИ, а не в маршрутах: маршрутов у треда с десяток, а тип
колонки знает один слой. Копия правила в маршрутах однажды разошлась бы с колонкой.
"""

from __future__ import annotations

import pytest

from service.services.chat.persistence.chat_repository import ChatRepository, _lookup_id


class _Boom:
    """Соединение, которого касаться НЕЛЬЗЯ: попытка = тот самый поход в БД."""

    def get_session_context(self):
        raise AssertionError("непредставимый идентификатор дошёл до запроса в БД")


@pytest.mark.parametrize("garbage", ["nope", "", "   ", "12345", "../etc/passwd", "null"])
def test_an_impossible_id_is_rejected_before_the_database(garbage):
    """⚠️ ГЛАВНОЕ. Отказ ДО запроса: дойдя до БД, он станет ошибкой типа, то есть 500."""
    assert _lookup_id(garbage) is None


@pytest.mark.parametrize(
    "value",
    [
        "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        "3F2504E0-4F89-11D3-9A0C-0305E82C3301",
        "  3f2504e0-4f89-11d3-9a0c-0305e82c3301  ",
    ],
)
def test_a_real_thread_id_still_passes(value):
    """🔴 ГРАНИЦА. «Чинить» так, чтобы перестали открываться настоящие треды, нельзя."""
    assert _lookup_id(value) == value.strip()


@pytest.mark.asyncio
async def test_the_owner_check_does_not_touch_the_database_on_garbage():
    """Точка входа всех маршрутов треда: владелец непредставимого — «никто», без запроса."""
    repo = ChatRepository.__new__(ChatRepository)
    repo._connector = _Boom()

    assert await repo.get_thread_owner("nope") is None


@pytest.mark.asyncio
async def test_the_primary_key_lookup_does_not_touch_the_database_on_garbage():
    """Вторая дверь в ту же таблицу — иначе починили бы половину."""
    repo = ChatRepository.__new__(ChatRepository)
    repo._connector = _Boom()

    assert await repo.get_thread_pk("nope") is None


@pytest.mark.asyncio
async def test_every_door_into_the_table_is_closed():
    """🔴 ЧЕТЫРЕ ДВЕРИ, А НЕ ДВЕ. Закрыть половину — значит починить только читающие пути.

    Удаление и переименование идут по тому же `thread_id` и точно так же роняли 500:
    проверка владельца их пропускает (владельца у несуществующего треда нет), и мусор
    доезжает до SQL. Страж перечисляет ВСЕ методы, которые ищут тред по внешнему ключу.
    """
    repo = ChatRepository.__new__(ChatRepository)
    repo._connector = _Boom()

    assert await repo.get_thread_owner("nope") is None
    assert await repo.get_thread_pk("nope") is None
    assert await repo.delete_thread("nope") == 0
    assert await repo.update_thread_title("nope", "новое имя") == 0


@pytest.mark.asyncio
async def test_a_valid_id_does_reach_the_database():
    """🔴 БЕЗ ЭТОГО тест выше зелен и от «всегда None»: проверка перестала бы что-то значить."""
    seen: dict = {}

    class _Result:
        def first(self):
            return (42,)

    class _Session:
        async def execute(self, _stmt, params):
            seen.update(params)
            return _Result()

    class _Ctx:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *exc):
            return False

    class _Connector:
        def get_session_context(self):
            return _Ctx()

    repo = ChatRepository.__new__(ChatRepository)
    repo._connector = _Connector()

    real = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
    assert await repo.get_thread_owner(real) == 42
    assert seen["thread_id"] == real
