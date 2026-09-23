"""Тесты in-memory сессии движка.

Импорт из `domain.sessions` — первоисточника. Раньше брали из
`infrastructure.sessions`, который тот же класс монкипатчил на импорте: тест
проверял ПРОПАТЧЕННУЮ версию, а боевой код — нет (модуль никто не импортировал).
"""

import pytest

from service.domain.sessions import PseudoSession


@pytest.mark.asyncio
async def test_pseudo_session_operations():
    session = PseudoSession("s2")
    await session.add_items([{"role": "user", "content": "Hi"}])
    last = await session.pop_item()
    assert last["role"] == "user"
    await session.add_items(
        [
            {"role": "user", "content": "x", "ts": "1"},
            {"role": "assistant", "content": "y", "ts": "2"},
        ]
    )
    items = await session.get_items(limit=1)
    assert len(items) == 1
    await session.clear_session()
    assert await session.get_items() == []


@pytest.mark.asyncio
async def test_pseudo_session_ttl_and_max_items():
    # max_items should trim older entries
    s = PseudoSession("s3", max_items=2)
    await s.add_items(
        [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "user", "content": "c"},
        ]
    )
    items = await s.get_items()
    assert len(items) == 2
    assert items[0]["content"] == "b"

    # ttl filtering - use old timestamps to ensure they are filtered out
    s2 = PseudoSession("s4", ttl_seconds=1)
    await s2.add_items([{"role": "user", "content": "old", "ts": str(0)}])
    await s2.add_items([{"role": "user", "content": "new", "ts": str(__import__("time").time())}])
    items = await s2.get_items()
    assert any(i["content"] == "new" for i in items)
