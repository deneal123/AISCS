"""Кэш сжатия контекста РАБОТАЕТ — и его отказ слышно.

⚠️ У этого кэша не было НИ ОДНОГО теста, при том что промах стоит до 39 провайдерских
вызовов на один запрос пользователя (map-reduce до 12 вызовов на секцию, секций три).

И он уже был мёртв целиком: сюда импортировался `RedisManager` из backend'а, которого в
сайдкаре нет; импорт стоял под `except`, падал молча, кэш не работал НИКОГДА. Заметить
это было нечем — ответы оставались правильными, менялся только счёт от провайдера.
Отсюда форма проверок: они считают ВЫЗОВЫ К МОДЕЛИ, а не только возвращаемый текст.
Текст при мёртвом кэше правильный — в этом и была проблема.

⚠️ Патчим `context_compressor.get_redis`, а не `shared.redis_client.get_redis`: компрессор
импортирует имя к себе (`from ... import get_redis`), и патч по месту объявления до него
не доедет.
"""

from __future__ import annotations

import logging

import pytest

from service.domain.pipeline import context_compressor as cc


async def _fixed_model() -> str:
    """Модель для сжатия резолвится ОДИН раз до map-фазы — подменяем её целиком.

    Иначе тест полез бы в сеть за каталогом моделей.
    """
    return "test-model"


class FakeRedis:
    """Минимальный async-Redis: get/set + управляемые отказы."""

    def __init__(self, *, fail_get: bool = False, fail_set: bool = False):
        self.store: dict[str, str] = {}
        self.fail_get = fail_get
        self.fail_set = fail_set
        self.sets: list[tuple[str, str, int | None]] = []

    async def get(self, key):
        if self.fail_get:
            raise ConnectionError("redis лёг на чтении")
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        if self.fail_set:
            raise ConnectionError("redis лёг на записи")
        self.store[key] = value
        self.sets.append((key, value, ex))


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(cc, "get_redis", lambda: fake)
    return fake


@pytest.fixture
def llm_calls(monkeypatch):
    """Счётчик обращений к модели. Это и есть деньги."""
    calls: list[str] = []

    async def _fake_summarize(text, target_tokens, kind, usage_out=None, model=""):
        calls.append(text)
        return "СЖАТО"

    monkeypatch.setattr(cc, "_summarize", _fake_summarize)
    monkeypatch.setattr(cc, "_pick_model", _fixed_model)
    return calls


# Заведомо длиннее любого используемого ниже target.
BIG = "абзац текста для сжатия. " * 400
TARGET = 100


# --------------------------------------------------------------------------- #
# Главное: попадание в кэш не платит                                            #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_cache_hit_costs_zero_llm_calls(redis, llm_calls):
    """⚠️ ГЛАВНОЕ СВОЙСТВО. Повтор того же сжатия не должен стоить ничего.

    Проверяем счётчик вызовов, а не текст: при полностью мёртвом кэше текст совпал бы
    тоже — просто оплаченный дважды.
    """
    first = await cc.compress_to_budget(BIG, TARGET)
    assert len(llm_calls) >= 1, "первое сжатие не сходило к модели — предпосылка неверна"
    spent = len(llm_calls)

    second = await cc.compress_to_budget(BIG, TARGET)

    assert second == first, "кэш вернул не то, что было записано"
    assert len(llm_calls) == spent, (
        f"повторное сжатие снова сходило к модели ({len(llm_calls) - spent} вызовов) — "
        "кэш не работает, платим за одну и ту же работу дважды"
    )


@pytest.mark.asyncio
async def test_result_is_actually_written_with_ttl(redis, llm_calls):
    """Запись состоялась и с TTL: без него кэш растёт неограниченно."""
    await cc.compress_to_budget(BIG, TARGET)

    assert redis.sets, "результат сжатия не записан в кэш вовсе"
    key, value, ex = redis.sets[-1]
    assert value == "СЖАТО"
    assert ex == cc._CACHE_TTL_SEC


# --------------------------------------------------------------------------- #
# Ключ: квантование бюджета                                                     #
# --------------------------------------------------------------------------- #
def test_target_drift_within_a_bucket_keeps_the_key():
    """⚠️ Доля секции плывёт от запроса к запросу — ключ плыть не должен.

    `target` пересчитывается от того, какие ДРУГИЕ секции присутствуют. Без квантования
    пользователь, задавший пять вопросов по одному файлу, получал пять новых ключей —
    пять промахов вместо четырёх попаданий.
    """
    base = cc._cache_key("текст", 2000, "files")

    assert cc._cache_key("текст", 2049, "files") == base
    assert cc._cache_key("текст", 2400, "files") == base


def test_clearly_different_budgets_do_not_share_a_key():
    """⚠️ Но склеивать заведомо разные бюджеты нельзя: пересказ на 500 токенов и на
    5000 — разные тексты, и отдать первый вместо второго значит тихо испортить контекст.
    """
    assert cc._cache_key("текст", 500, "files") != cc._cache_key("текст", 5000, "files")


def test_key_separates_content_and_kind():
    assert cc._cache_key("A", 1000, "files") != cc._cache_key("B", 1000, "files")
    assert cc._cache_key("A", 1000, "files") != cc._cache_key("A", 1000, "memory")


# --------------------------------------------------------------------------- #
# Отказы Redis: работаем, но не молча                                           #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_write_failure_is_loud(monkeypatch, llm_calls, caplog):
    """⚠️ Отказ ЗАПИСИ обязан быть слышен — раньше он глушился в `pass`.

    Это единственный отказ, который не виден больше ниоткуда: чтение молча промахивается,
    сжатие честно считается заново, ответ пользователю правильный. Наружу — только счёт
    от провайдера. Ровно так кэш и был мёртв всё время.
    """
    monkeypatch.setattr(cc, "get_redis", lambda: FakeRedis(fail_set=True))

    with caplog.at_level(logging.WARNING):
        result = await cc.compress_to_budget(BIG, TARGET)

    assert result == "СЖАТО", "отказ кэша не должен ломать сам ответ"
    assert any("compression cache write unavailable" in r.message for r in caplog.records), (
        "неудачная запись в кэш не оставила следа — деньги утекают беззвучно"
    )


@pytest.mark.asyncio
async def test_read_failure_degrades_to_computing(monkeypatch, llm_calls, caplog):
    """Отказ чтения — fail-open: считаем заново, запрос не роняем."""
    monkeypatch.setattr(cc, "get_redis", lambda: FakeRedis(fail_get=True))

    with caplog.at_level(logging.WARNING):
        result = await cc.compress_to_budget(BIG, TARGET)

    assert result == "СЖАТО"
    assert llm_calls, "при недоступном кэше сжатие обязано выполниться"


@pytest.mark.asyncio
async def test_no_redis_at_all_still_works(monkeypatch, llm_calls):
    """Redis не сконфигурен (`None`) — путь обязан работать целиком."""
    monkeypatch.setattr(cc, "get_redis", lambda: None)

    assert await cc.compress_to_budget(BIG, TARGET) == "СЖАТО"


# --------------------------------------------------------------------------- #
# Вырожденные входы                                                             #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_text_that_fits_never_touches_the_model(redis, llm_calls):
    """⚠️ Влезает в бюджет — ни модели, ни кэша. Иначе платим за пустую работу."""
    result = await cc.compress_to_budget("короткий текст", 5000)

    assert result == "короткий текст"
    assert not llm_calls, "текст влезал в бюджет, но за него всё равно заплатили"
    assert not redis.sets


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "target"),
    [("", 1000), ("   ", 1000), (BIG, 0), (BIG, -1)],
    ids=["пусто", "пробелы", "нулевой бюджет", "отрицательный бюджет"],
)
async def test_degenerate_input_returns_empty_without_paying(redis, llm_calls, raw, target):
    assert await cc.compress_to_budget(raw, target) == ""
    assert not llm_calls


# --------------------------------------------------------------------------- #
# Каталог моделей — один раз на map-reduce, а не на каждый кусок                 #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_catalog_is_resolved_once_per_compression(monkeypatch):
    """⚠️ Резолв модели стоял ВНУТРИ `_summarize`, то есть на КАЖДЫЙ кусок.

    До 12 кусков на секцию, секций три, и все три сжимаются параллельно — до ~36
    обращений к каталогу на один запрос. При тёплом кэше это дёшево, но у
    `list_available_models` нет single-flight: в момент истечения TTL все они уходят в
    перестройку одновременно, а перестройка — это `gather` по пяти провайдерам с
    таймаутом на каждого. Самый дорогой момент совпадал с самым многолюдным.

    ⚠️ ЗДЕСЬ НЕЛЬЗЯ ПОДМЕНЯТЬ `_summarize`. Первая версия этого теста так и делала и была
    ФАЛЬШИВОЙ: мутация «вернуть резолв внутрь куска» оставалась зелёной. Причин две —
    подменённый `_summarize` до резолва вообще не доходит, а `assert` внутри фейка
    глотается собственным `except` компрессора («сжатие куска не удалось — фрагмент
    выпал»). Поэтому подменяется ТРАНСПОРТ (`create_chat_completion`), а сам
    `_summarize` работает настоящий.
    """
    from types import SimpleNamespace

    calls = {"catalog": 0}

    async def _counting_catalog():
        calls["catalog"] += 1
        return ["test-model"]

    async def _fake_completion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="СЖАТО"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    import service.domain.client as client_mod
    import service.domain.subagents.utils as utils_mod

    monkeypatch.setattr(client_mod, "list_qualified_models", _counting_catalog)
    monkeypatch.setattr(client_mod, "create_chat_completion", _fake_completion)
    monkeypatch.setattr(utils_mod, "pick_text_model", lambda models: "test-model")
    monkeypatch.setattr(cc, "get_redis", lambda: None)

    # Текст заведомо на несколько кусков: иначе «один раз» получится случайно.
    huge = "\n\n".join(f"абзац номер {i} " + "слово " * 400 for i in range(30))
    result = await cc.compress_to_budget(huge, 300)

    assert result, "сжатие не отработало — предпосылка теста неверна"
    assert calls["catalog"] == 1, (
        f"каталог запрошен {calls['catalog']} раз(а) на одно сжатие — резолв снова "
        "выполняется на каждый кусок"
    )
