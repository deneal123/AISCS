"""Мёртвые идентификаторы файлов треда не выдаются за «файлов не было».

🔴 НАЙДЕНО ПО ОТЧЁТУ ЧЕЛОВЕКА И ЗАМЕРУ ЖИВОГО СТЕКА. Он приложил код и получил: «В
предоставленном рабочем каталоге отсутствуют файлы для анализа. Если вы прикладывали архив
или код, они, к сожалению, не загрузились». 27k токенов, 6570 кредитов, ответа нет.

Замер по стеку:
* `chat:<тред>:file_ids` в Redis = один идентификатор, TTL живой;
* записи с этим идентификатором в `profile.user_file` НЕТ ВОВСЕ;
* песочница треда создана, в её истории только «песочница создана» — записи «файлы
  пользователя» нет, каталог пуст.

Цепочка молчала на каждом звене: набор идентификаторов помнится два часа и с БД НЕ
СВЕРЯЕТСЯ; мёртвый идентификатор даёт пустой список ссылок; пустой список неотличим от
«файлов не прикладывали»; `import_files(ref, [])` штатно ничего не кладёт. В итоге агент
честно сообщает человеку, что файлов нет, — и это единственное место, где видно поломку.

Хуже всего, что память переживала бы КАЖДЫЙ следующий ход: те же мёртвые идентификаторы,
тот же пустой каталог, тот же ответ. Поэтому набор чистится, а расхождение попадает в лог.
"""

from __future__ import annotations

import logging

import pytest

from service.services.chat.infrastructure import agent_context

_LOGGER_NAME = "service.services.chat.infrastructure.agent_context"


@pytest.fixture(autouse=True)
def _logs_reach_caplog(caplog):
    """Логгер `service` объявлен с `propagate: False` — цепляем хендлер прямо к нему.

    ⚠️ Иначе тест зелёный в одиночку и красный в наборе (или наоборот): порядок импортов
    решает, доходит ли запись до перехватчика pytest. Третий случай в проекте.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.addHandler(caplog.handler)
    previous = logger.level
    logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        logger.removeHandler(caplog.handler)
        logger.setLevel(previous)


class _Redis:
    """Двойник СИНХРОННОГО клиента воркера: команды — обычные методы.

    ⚠️ Форма важна: в воркере клиент синхронный, вызовы уводятся в `to_thread`. Двойник с
    `async def` прошёл бы мимо этой границы и проверял бы не то.
    """

    def __init__(self, stored: str | None = None):
        self.stored = stored
        self.deleted: list[str] = []

    def get(self, key):
        return self.stored

    def set(self, key, value, ex=None):
        self.stored = value

    def delete(self, key):
        self.deleted.append(key)
        self.stored = None


# --- мёртвый набор чистится -------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_fully_dead_set_is_forgotten(monkeypatch, caplog):
    """🔴 ГЛАВНОЕ. Иначе те же мёртвые идентификаторы просятся КАЖДЫЙ ход, и каждый ход
    человек получает «файлов нет» при приложенных файлах."""
    redis = _Redis('["53306357-61ef-4706-b946-3a9faa6e24e3"]')

    async def _no_links(_user_id, *, file_ids=None):
        return []

    monkeypatch.setattr(agent_context, "list_user_dialog_file_links", _no_links)
    monkeypatch.setattr(agent_context, "list_user_tabular_file_links", _no_links)

    with caplog.at_level("WARNING"):
        tabular, dialog = await agent_context.collect_thread_files(redis, "t-1", "u-1", {})

    assert dialog == []
    assert redis.deleted == ["chat:t-1:file_ids"], "мёртвая память треда пережила ход"
    assert any("стёрта" in r.message.lower() for r in caplog.records), (
        "набор стёрт МОЛЧА — узнать об этом было бы нельзя"
    )


@pytest.mark.asyncio
async def test_a_living_set_is_kept(monkeypatch):
    """🔴 ГРАНИЦА. Стереть живой набор значило бы потерять файлы follow-up'а — то есть
    завести ровно ту поломку, от которой память треда и заведена."""
    redis = _Redis('["alive-1"]')

    async def _links(_user_id, *, file_ids=None):
        return [{"name": "смета.xlsx", "url": "https://s/1"}]

    monkeypatch.setattr(agent_context, "list_user_dialog_file_links", _links)
    monkeypatch.setattr(agent_context, "list_user_tabular_file_links", _links)

    _, dialog = await agent_context.collect_thread_files(redis, "t-1", "u-1", {})

    assert dialog and redis.deleted == [], "живая память треда стёрта — файлы потеряются"


@pytest.mark.asyncio
async def test_a_partially_dead_set_is_kept(monkeypatch):
    """🔴 ГРАНИЦА, ВАЖНЕЕ ПРЕДЫДУЩЕЙ. Один файл удалён, второй на месте — стирать весь
    набор нельзя: живой файл исчез бы из песочницы вслед за мёртвым."""
    redis = _Redis('["dead-1", "alive-2"]')

    async def _one(_user_id, *, file_ids=None):
        return [{"name": "живой.py", "url": "https://s/2"}]

    monkeypatch.setattr(agent_context, "list_user_dialog_file_links", _one)
    monkeypatch.setattr(agent_context, "list_user_tabular_file_links", _one)

    _, dialog = await agent_context.collect_thread_files(redis, "t-1", "u-1", {})

    assert len(dialog) == 1
    assert redis.deleted == [], "частичная потеря стёрла весь набор"


@pytest.mark.asyncio
async def test_an_empty_set_does_not_touch_redis(monkeypatch):
    """⚠️ Файлов не прикладывали — стирать нечего, и ходить в Redis незачем."""
    redis = _Redis(None)

    async def _no_links(_user_id, *, file_ids=None):
        return []

    monkeypatch.setattr(agent_context, "list_user_dialog_file_links", _no_links)
    monkeypatch.setattr(agent_context, "list_user_tabular_file_links", _no_links)

    await agent_context.collect_thread_files(redis, "t-1", "u-1", {})

    assert redis.deleted == []


@pytest.mark.asyncio
async def test_a_broken_redis_does_not_break_the_turn(monkeypatch, caplog):
    """⚠️ Redis тут КЭШ, а не источник истины: не смогли стереть — ход всё равно идёт."""

    class _Broken(_Redis):
        def delete(self, key):
            raise RuntimeError("redis лёг")

    async def _no_links(_user_id, *, file_ids=None):
        return []

    monkeypatch.setattr(agent_context, "list_user_dialog_file_links", _no_links)
    monkeypatch.setattr(agent_context, "list_user_tabular_file_links", _no_links)

    with caplog.at_level("WARNING"):
        tabular, dialog = await agent_context.collect_thread_files(
            _Broken('["dead"]'), "t-1", "u-1", {}
        )

    assert dialog == [] and tabular == [], "ход упал из-за недоступного Redis"


# --- расхождение с базой называется вслух ------------------------------------------------ #


def test_losing_everything_is_reported_as_a_breakage(caplog):
    """🔴 «Запросили файлы и не нашли ни одного» — поломка, а не «файлов нет». Без записи в
    лог единственным её следом остаётся жалоба человека, что файлы «не загрузились»."""
    with caplog.at_level("WARNING"):
        agent_context._report_missing_rows({"dead-1", "dead-2"}, 0)

    messages = " ".join(r.getMessage().lower() for r in caplog.records)
    assert "не найдены в базе" in messages, "полная потеря файлов молчит"
    assert "песочница останется пустой" in messages, "не сказано, чем это кончится для человека"
    assert "dead-1" in messages, "идентификаторы не названы — разбираться будет нечем"


def test_losing_part_is_reported_differently(caplog):
    """⚠️ Числа несущие: «потеряно всё» и «потеряна часть» — разные поломки с разными
    причинами, и путать их в одном сообщении значит лечить не то."""
    with caplog.at_level("WARNING"):
        agent_context._report_missing_rows({"a", "b", "c"}, 2)

    messages = " ".join(r.getMessage().lower() for r in caplog.records)
    assert "часть файлов" in messages
    assert "неполному набору" in messages, "не сказано, что ответ будет по неполным данным"


def test_a_complete_set_says_nothing(caplog):
    """🔴 ГРАНИЦА. Всё нашлось — предупреждать не о чем: шум в логе прячет настоящие поломки."""
    with caplog.at_level("WARNING"):
        agent_context._report_missing_rows({"a", "b"}, 2)
        agent_context._report_missing_rows(None, 0)
        agent_context._report_missing_rows(set(), 0)

    assert not caplog.records, "предупреждение выдано там, где всё в порядке"
