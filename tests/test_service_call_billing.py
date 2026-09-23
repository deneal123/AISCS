"""Служебные LLM-вызовы попадают в счёт.

⚠️ ТРИ ДЫРЫ, ВСЕ НА ГОРЯЧЕМ ПУТИ. Учёт токенов в этом сервисе проходил несколько раундов
аудита (комментарии ссылаются на P0.3, A2, A4), и в покрытых местах дисциплина
образцовая. Но ровно три вызова остались бесплатными для платформы:

1. **Роутер оркестратора** — единственный LLM-вызов, у которого вообще не было
   накопителя, ни на MWS-ветке, ни на SDK. Срабатывает практически на КАЖДОМ сообщении:
   при ручном выборе модели `route_model` уходит в `source:"manual"` без ключа `tool`,
   `route_override` остаётся пустым, и процессор зовёт роутер.
2. **Выбор модели на пути `/run`** — починка аудита A2 доехала до `/route`
   (`model_routing_service` передаёт накопитель), но не до `RouteModelUseCase`. Боевой
   WS-путь идёт именно через `/run`.
3. **Сжатие контекста** — до 12 map-вызовов + reduce НА СЕКЦИЮ, сжимаемых секций три.
   До 39 неоплаченных вызовов на один запрос, причём ровно на самых дорогих (большое
   вложение).

Тесты проверяют, что накопитель ДОХОДИТ, а не что функция его принимает: параметр можно
объявить и не передать — именно так дыра №2 и прожила аудит.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def _resp(prompt: int, completion: int, content: str = "{}"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
        ),
    )


# --------------------------------------------------------------------------- #
# 1. Роутер оркестратора                                                        #
# --------------------------------------------------------------------------- #


class _NullLogger:
    def exception(self, *_a, **_k):
        pass

    def info(self, *_a, **_k):
        pass


# --------------------------------------------------------------------------- #
# 2. Выбор модели на пути /run                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_route_model_use_case_forwards_usage(monkeypatch):
    """⚠️ Именно ЭТА половина A2 не была починена: `/route` накопитель передавал, а
    `/run` — нет, при том что боевой трафик идёт через `/run`."""
    from service.application.use_cases import agent_execution_use_cases as uc
    from service.domain.run_context import RunExecutionContext

    async def _fake_route_model(*, text, selected_model, input_type, execution=None):
        assert execution is not None, "RouteModelUseCase не передал run context"
        execution.usage.record_usage(
            {"prompt": 25, "completion": 3}, model="router-m", kind="route_model"
        )
        return "m1", {"source": "llm"}

    monkeypatch.setattr(uc, "route_model", _fake_route_model)

    execution = RunExecutionContext()
    model, _meta = await uc.RouteModelUseCase().execute(
        text="запрос", selected_model=None, input_type=None, execution=execution
    )

    assert model == "m1"
    assert execution.usage.prompt_tokens == 25


def test_reply_assembler_accepts_pre_run_usage():
    """Вызов, сделанный ДО прогона процессора, тоже попадает в счёт.

    Событий ему эмитить некуда — процессор ещё не запущен, — поэтому нужен явный вход.
    """
    from service.application.reply_assembler import ReplyAssembler

    assembler = ReplyAssembler()
    assembler.add_usage({"prompt": 25, "completion": 3, "model": "router-m"})

    assert assembler.prompt_tokens == 25
    assert assembler.completion_tokens == 3
    assert assembler.per_call_usage == [{"model": "router-m", "prompt": 25, "completion": 3}]


# --------------------------------------------------------------------------- #
# 3. Сжатие контекста                                                           #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_compression_bills_every_chunk(monkeypatch):
    """Каждый map-вызов и reduce попадают в накопитель.

    ⚠️ Проверяем СУММУ по нескольким кускам, а не факт «хоть что-то записалось»: дыра
    была в том, что вызовов много, и потерять их можно было пачкой.
    """
    from service.domain.pipeline import context_compressor as cc

    calls = {"n": 0}

    async def _fake_create(**kwargs):
        calls["n"] += 1
        return _resp(100, 20, content="краткий пересказ")

    # Кэш выключаем: предмет теста — учёт вызовов, а не попадание в Redis.
    monkeypatch.setattr(cc, "get_redis", lambda: None)

    import service.domain.client as client_pkg

    monkeypatch.setattr(client_pkg, "create_chat_completion", _fake_create)

    async def _models():
        return ["gpt-4o-mini"]

    monkeypatch.setattr(client_pkg, "list_qualified_models", _models)

    raw = "\n\n".join(f"абзац номер {i} с содержательным текстом" for i in range(400))

    from service.domain.run_context import RunExecutionContext

    execution = RunExecutionContext()
    await cc.compress_to_budget(raw, target=900, kind="memory", execution=execution)

    assert calls["n"] >= 2, "тест бессмыслен, если сжатие уложилось в один вызов"
    assert execution.usage.prompt_tokens == 100 * calls["n"], "потерян usage части вызовов"
    assert {receipt.model for receipt in execution.usage.receipts} == {"gpt-4o-mini"}


@pytest.mark.asyncio
async def test_compressor_factory_carries_the_accumulator(monkeypatch):
    """⚠️ Накопитель захватывается ЗАМЫКАНИЕМ фабрики, а не расширяет контракт
    `Compressor`: ассемблер про биллинг знать не должен.

    Тест держит именно эту связку — иначе `usage_out` можно было бы добавить в
    `_summarize` и не протащить до вызывающего, что и было исходной ошибкой.
    """
    from service.domain.pipeline import context_compressor as cc

    seen: dict = {}

    async def _fake_compress(raw, target, kind, *, execution=None):
        seen["execution"] = execution
        return "сжато"

    monkeypatch.setattr(cc, "compress_to_budget", _fake_compress)

    from service.domain.run_context import RunExecutionContext

    execution = RunExecutionContext()
    compressor = cc.make_compressor(
        SimpleNamespace(agents=SimpleNamespace(context_compression_enabled=True)),
        execution=execution,
    )
    out = await compressor("текст", 500, "files")

    assert out == "сжато"
    assert seen["execution"] is execution, "фабрика не донесла run context до сжатия"


# --------------------------------------------------------------------------- #
# Кэш сжатия                                                                    #
# --------------------------------------------------------------------------- #
def test_cache_key_survives_budget_drift():
    """⚠️ Кэш промахивался ПО УСТРОЙСТВУ: в ключ входил точный `target`.

    А `target` — доля секции, которая пересчитывается от того, какие другие секции
    присутствуют. Пользователь приложил файл и задал пять вопросов: история растёт, доля
    файла плывёт на десятки токенов, ключ каждый раз новый. Пять промахов вместо четырёх
    попаданий, каждый промах — до 13 провайдерских вызовов.
    """
    from service.domain.pipeline.context_compressor import _cache_key

    assert _cache_key("текст", 2000, "files") == _cache_key("текст", 2180, "files")


def test_cache_key_still_separates_different_budgets():
    """Обратная сторона: пересказ на 500 токенов и на 5000 — разные тексты.

    Склеить их значило бы тихо ухудшить контекст, отдав слишком короткий пересказ там,
    где места было втрое больше.
    """
    from service.domain.pipeline.context_compressor import _cache_key

    assert _cache_key("текст", 500, "files") != _cache_key("текст", 5000, "files")
    assert _cache_key("текст", 900, "files") != _cache_key("текст", 900, "memory")
