"""Тайминги шагов и БЮДЖЕТ провайдерских вызовов.

⚠️ ЗАЧЕМ ЭТО ПОЯВИЛОСЬ. У сайдкара не было ни одного замера времени по шагам конвейера:
единственный `perf_counter` во всём сервисе стоял в клиенте соседних сервисов. Из этого
следовали две вещи, обе плохие:

* «стало быстрее» проверить было нечем — любая оптимизация оставалась утверждением;
* новый служебный LLM-вызов можно было добавить и не заметить. А их и так до четырёх до
  первого видимого токена (роутинг модели, роутер оркестратора, оценка сложности, план),
  и каждый — деньги и задержка на КАЖДОМ сообщении.

Бюджет ниже — не «оптимальное» число, а ЗАФИКСИРОВАННОЕ ТЕКУЩЕЕ. Смысл в том, чтобы рост
требовал явного решения, а не проходил молча.
"""

from __future__ import annotations

import pytest

from service.domain.client.protocol import ProviderRoundState
from service.shared import step_timing


# --------------------------------------------------------------------------- #
# Сам сборщик                                                                   #
# --------------------------------------------------------------------------- #
def test_collector_is_off_outside_a_run():
    """Вне прогона сбор ничего не делает и не аллоцирует.

    Важно не для скорости, а по смыслу: `/v1`-шлюз зовут memos/ldr/graphify по чужому
    протоколу, и навешивать на них сбор шагов нашего конвейера незачем.
    """
    assert step_timing.current() is None

    with step_timing.step("вне-прогона"):
        pass
    step_timing.count_llm_call("какая-то-модель")  # не должно падать

    assert step_timing.current() is None


def test_steps_and_calls_are_collected():
    with step_timing.collect() as timings:
        with step_timing.step("routing"):
            pass
        step_timing.count_llm_call("gpt-4o-mini")
        step_timing.count_llm_call("gpt-4o-mini")

    meta = timings.as_meta()

    assert meta["llm_calls"] == 2
    assert meta["llm_models"] == {"gpt-4o-mini": 2}
    assert "routing" in meta["steps_ms"]


def test_repeated_step_sums_instead_of_overwriting():
    """Шаг может выполняться несколько раз за прогон — раунды инструментов, секции
    контекста. Интересна ОБЩАЯ доля, а не последняя итерация."""
    with step_timing.collect() as timings:
        for _ in range(3):
            with step_timing.step("tool_round"):
                pass

    assert timings.steps_ms["tool_round"] >= 0.0
    assert list(timings.steps_ms) == ["tool_round"]


def test_collector_is_restored_after_nested_runs():
    """Вложенный прогон не должен затирать внешний: у каждого свой сборщик."""
    with step_timing.collect() as outer:
        step_timing.count_llm_call("a")
        with step_timing.collect() as inner:
            step_timing.count_llm_call("b")
        assert inner.llm_calls == 1
        step_timing.count_llm_call("c")

    assert outer.llm_calls == 2, "внутренний прогон не должен попадать во внешний счёт"


# --------------------------------------------------------------------------- #
# БЮДЖЕТ: счётчик нельзя обойти                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_every_provider_call_is_counted(monkeypatch):
    """⚠️ Счётчик стоит в ЕДИНСТВЕННОЙ точке на путь — в фасаде провайдеров.

    Если бы его инкрементировали вызывающие, новый путь к провайдеру можно было бы
    завести мимо счётчика, и бюджет перестал бы что-либо гарантировать ровно тогда,
    когда он нужнее всего. Здесь это и проверяется: зовём фасад, а не счётчик.
    """
    from service.domain.client.calls import chat

    async def _fake_order(_active):
        return ["p1"]

    monkeypatch.setattr(chat, "build_provider_order", lambda _a: ["p1"])
    monkeypatch.setattr(chat, "get_provider_module", lambda _n: None)

    with step_timing.collect() as timings:
        with pytest.raises(RuntimeError):
            await chat.create_chat_completion(messages=[], model="m1")

    assert timings.llm_calls == 1, "вызов фасада обязан быть посчитан даже при неудаче"
    assert timings.llm_models == {"m1": 1}


@pytest.mark.asyncio
async def test_failover_attempts_count_as_one_logical_call(monkeypatch):
    """⚠️ Считаем ЛОГИЧЕСКИЙ вызов, а не попытку.

    Иначе бюджет рос бы от деградации провайдеров, а не от нашего кода: тест «служебных
    вызовов не больше N» краснел бы по чужой вине, и его бы отключили.
    """
    from service.domain.client.calls import chat

    class _Boom:
        OPENAI_CLIENT = object()

        @staticmethod
        async def create_chat_completion(*_a, **_k):
            raise RuntimeError("провайдер лёг")

    monkeypatch.setattr(chat, "build_provider_order", lambda _a: ["p1", "p2", "p3"])
    monkeypatch.setattr(chat, "get_provider_module", lambda _n: _Boom())
    monkeypatch.setattr(chat, "retry_params", lambda: {"attempts": 1})

    async def _cat():
        return [], {}

    monkeypatch.setattr(chat, "get_model_catalog", _cat)

    async def _qualify(_name, *, prefer=None, requirement=None, **_kwargs):
        from service.domain.client.model_catalog import ModelCatalogSource, ModelCatalogStatus
        from service.domain.client.model_requirements import (
            ModelQualification,
            ModelRequirement,
            ProviderQualificationStatus,
        )

        return ModelQualification(
            provider="p1",
            requirement=requirement or ModelRequirement.CHAT,
            status=ProviderQualificationStatus.COMPATIBLE,
            catalog_source=ModelCatalogSource.LIVE,
            catalog_status=ModelCatalogStatus.AVAILABLE,
            candidate_count=1,
            model=prefer,
        )

    monkeypatch.setattr(chat, "qualify_model", _qualify)

    with step_timing.collect() as timings:
        with pytest.raises(RuntimeError):
            await chat.create_chat_completion(messages=[], model="m1")

    assert timings.llm_calls == 1, "три попытки фейловера — это один логический вызов"


@pytest.mark.asyncio
async def test_streaming_calls_are_counted_too(monkeypatch):
    """⚠️ Стрим — ОСНОВНОЙ путь ответа, и он считается отдельной функцией.

    Мутация показала дыру: я покрыл только `chat.py`, и удаление счётчика из
    `streaming.py` оставляло набор зелёным — то есть бюджет не сторожил как раз тот
    путь, по которому идёт каждый ответ пользователю.
    """
    from service.domain.client.calls import streaming

    monkeypatch.setattr(streaming, "build_provider_order", lambda _a: [])
    monkeypatch.setattr(streaming.active, "ACTIVE_PROVIDER", "p1")

    async def _cat():
        return [], {}

    monkeypatch.setattr(streaming, "get_model_catalog", _cat)

    async def _passthrough(order):
        return list(order)

    monkeypatch.setattr(streaming.provider_policy, "drop_hard_off", _passthrough)

    with step_timing.collect() as timings:
        with pytest.raises(RuntimeError):
            async for _ in streaming.stream_provider_completion(
                [{"role": "user", "content": "x"}],
                "m1",
                round_state=ProviderRoundState(),
            ):
                pass

    assert timings.llm_calls == 1
    assert timings.llm_models == {"m1": 1}


def test_context_is_restored_even_when_the_run_fails():
    """Сборщик обязан сняться и на исключении.

    Иначе один упавший прогон оставил бы свой сборщик активным на весь процесс, и
    следующие запросы дописывали бы шаги в чужой отчёт — тайминги стали бы врать тем
    сильнее, чем дольше живёт воркер.
    """
    assert step_timing.current() is None

    with pytest.raises(ValueError):
        with step_timing.collect():
            assert step_timing.current() is not None
            raise ValueError("прогон упал")

    assert step_timing.current() is None, "сборщик протёк наружу после сбоя"


# --------------------------------------------------------------------------- #
# Мемоизация capability модели                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_tool_support_is_resolved_once_per_catalog_generation(monkeypatch):
    """⚠️ На одном запросе проверка идёт до ПЯТИ раз.

    Гейт `_auto_knowledge`, гейт стрима и по разу на каждого провайдера внутри цикла
    фейловера. Каждый раз — разбор строки, обход allowlist и префиксов, перебор пяти
    вариантов ключа в `resolve_model_meta`. Ответ при неизменном каталоге один и тот же.
    """
    from service.shared import model_catalog as mc

    mc._TOOL_SUPPORT_MEMO.clear()
    calls = {"n": 0}

    def _counting_resolve(mid, catalog=None):
        calls["n"] += 1
        return {"capabilities": ["tools"]}

    monkeypatch.setattr(mc, "resolve_model_meta", _counting_resolve)

    async def _catalog():
        return {"m1": {"capabilities": ["tools"]}}

    monkeypatch.setattr(mc, "get_openrouter_catalog", _catalog)

    for _ in range(5):
        assert await mc.model_supports_tools("some/model-1") is True

    assert calls["n"] == 1, f"capability разрешалась {calls['n']} раз вместо одного"


@pytest.mark.asyncio
async def test_tool_support_memo_expires_with_the_catalog(monkeypatch):
    """⚠️ Обратная сторона: вечный кэш означал бы, что у модели, которой ДОБАВИЛИ
    инструменты, они не появятся никогда.

    Поэтому ключ мемо включает поколение каталога, а не время.
    """
    from service.shared import model_catalog as mc

    mc._TOOL_SUPPORT_MEMO.clear()
    caps = {"value": []}

    monkeypatch.setattr(
        mc, "resolve_model_meta", lambda mid, catalog=None: {"capabilities": caps["value"]}
    )

    async def _catalog():
        return {}

    monkeypatch.setattr(mc, "get_openrouter_catalog", _catalog)

    mc._cache["ts"] = 1000.0
    assert await mc.model_supports_tools("some/model-2") is False

    # Каталог обновился, и у модели появились инструменты.
    caps["value"] = ["tools"]
    mc._cache["ts"] = 2000.0

    assert await mc.model_supports_tools("some/model-2") is True, (
        "мемо пережило обновление каталога"
    )
