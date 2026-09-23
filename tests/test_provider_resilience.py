"""Тесты реестра провайдеров, ретраев и фейловера стрима (Фаза 1)."""

from unittest.mock import patch

import httpx
import pytest

# ⚠️ Патчим МОДУЛИ-ВЛАДЕЛЬЦЫ, а не фасад пакета: `chat.py` и `streaming.py` берут
# `build_provider_order`/`resolve_model_for` себе на импорте, и подмена на фасаде до них
# не доходит. Пока всё лежало в `__init__.py`, фасад и владелец совпадали.
import service.domain.client.active as active
import service.domain.client.calls.chat as chat
import service.domain.client.calls.streaming as streaming
from service.domain.client import registry
from service.domain.client.calls import retry
from service.domain.client.model_catalog import ModelCatalogSource, ModelCatalogStatus
from service.domain.client.model_requirements import (
    ModelQualification,
    ModelRequirement,
    ProviderQualificationStatus,
)
from service.domain.client.protocol import ProviderProtocolError, ProviderRoundState
from service.settings import config


async def _stream(messages, model, **kwargs):
    state = kwargs.pop("round_state", None) or ProviderRoundState()
    async for delta in streaming.stream_provider_completion(
        messages, model, round_state=state, **kwargs
    ):
        yield delta


@pytest.fixture(autouse=True)
def _reset_circuit_breaker():
    # Circuit breaker держит in-memory состояние в module-global — чистим, чтобы падение
    # провайдера в одном тесте не выбивало его из ротации в следующем.
    from service.domain.client.resilience import circuit_breaker

    circuit_breaker._DOWN_UNTIL.clear()
    yield
    circuit_breaker._DOWN_UNTIL.clear()


# --------------------------------------------------------------------------- #
# classify_error / with_retry                                                  #
# --------------------------------------------------------------------------- #
def test_classify_error_categories():
    assert retry.classify_error(httpx.ConnectError("x")) == "transient"
    assert retry.classify_error(httpx.TimeoutException("x")) == "timeout"
    assert retry.classify_error(TimeoutError()) == "timeout"
    assert retry.classify_error(RuntimeError("not configured")) == "fatal"


def test_is_retryable():
    assert retry.is_retryable(httpx.ConnectError("x")) is True
    assert retry.is_retryable(RuntimeError("nope")) is False


@pytest.mark.asyncio
async def test_with_retry_retries_transient_then_succeeds(monkeypatch):
    sleeps: list[float] = []

    async def _fake_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr(retry.asyncio, "sleep", _fake_sleep)

    calls = {"n": 0}

    async def _fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("flaky")
        return "ok"

    out = await retry.with_retry(_fn, attempts=3, base_delay=0.01, max_delay=0.02)
    assert out == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2  # два ретрая


@pytest.mark.asyncio
async def test_with_retry_does_not_retry_non_retryable(monkeypatch):
    calls = {"n": 0}

    async def _fn():
        calls["n"] += 1
        raise RuntimeError("fatal")

    with pytest.raises(RuntimeError):
        await retry.with_retry(_fn, attempts=5)
    assert calls["n"] == 1  # без ретраев


# --------------------------------------------------------------------------- #
# build_provider_order                                                          #
# --------------------------------------------------------------------------- #
@pytest.fixture
def config_only_settings(monkeypatch):
    """Изолировать порядок провайдеров от runtime-оверлея админки.

    `build_provider_order` читает настройку через `runtime_settings.get_agents(...)`, то
    есть оверлей БЬЁТ значение из config. Тест патчит только config — и потому зависел от
    того, оставил ли кто-то из соседних тестов значение в глобальном оверлее (синглтон
    живёт весь прогон). Отсюда «падает только в полном прогоне». Заставляем оверлей
    отдавать дефолт: тест проверяет config-driven порядок, а не состояние соседей.
    """
    monkeypatch.setattr(registry.runtime_settings, "get_agents", lambda _key, default=None: default)


def test_provider_order_single_when_failover_off(monkeypatch, config_only_settings):
    monkeypatch.setattr(config.agents, "provider_failover_enabled", False)
    monkeypatch.setattr(config.agents, "provider_fallback_order", "openrouter,gigachat")
    assert registry.build_provider_order("mws") == ["mws"]


def test_provider_order_includes_configured_fallbacks(monkeypatch, config_only_settings):
    monkeypatch.setattr(config.agents, "provider_failover_enabled", True)
    monkeypatch.setattr(config.agents, "provider_fallback_order", "gigachat,openrouter,mws")
    monkeypatch.setattr(registry, "is_configured", lambda name: name in {"gigachat", "openrouter"})
    order = registry.build_provider_order("mws")
    # primary первым, дубликат mws не добавляется повторно, неконфигурированные — мимо
    assert order == ["mws", "gigachat", "openrouter"]


# --------------------------------------------------------------------------- #
# stream_chat_completion failover boundary                                     #
# --------------------------------------------------------------------------- #
class _Delta:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content):
        self.choices = [_Choice(content)]
        self.usage = None


async def _agen(chunks, raise_at=None):
    for i, c in enumerate(chunks):
        if raise_at is not None and i == raise_at:
            raise httpx.ConnectError("mid-stream")
        yield _Chunk(c)


class _Completions:
    def __init__(self, behavior, spy):
        self._behavior = behavior
        self._spy = spy

    async def create(self, **payload):
        self._spy.append(payload.get("model"))
        return self._behavior()


class _Client:
    def __init__(self, behavior, spy):
        self.chat = type("C", (), {"completions": _Completions(behavior, spy)})()


def _patch_two_providers(monkeypatch, primary_behavior, secondary_behavior):
    spy_p, spy_s = [], []
    modules = {
        "p1": type("M", (), {"OPENAI_CLIENT": _Client(primary_behavior, spy_p)})(),
        "p2": type("M", (), {"OPENAI_CLIENT": _Client(secondary_behavior, spy_s)})(),
    }
    monkeypatch.setattr(streaming, "build_provider_order", lambda _p: ["p1", "p2"])
    monkeypatch.setattr(streaming, "get_provider_module", lambda n: modules.get(n))
    # primary — активный провайдер: использует get_openai_client() и получает
    # выбранную модель как есть; вторичный резолвит совместимую при фейловере.
    monkeypatch.setattr(active, "ACTIVE_PROVIDER", "p1")
    monkeypatch.setattr(active, "get_openai_client", lambda: modules["p1"].OPENAI_CLIENT)

    async def _qualify(name, *, prefer=None, requirement=None, **_kwargs):
        model = prefer if name == "p1" else "model-" + name
        return ModelQualification(
            provider=name,
            requirement=requirement or ModelRequirement(),
            status=ProviderQualificationStatus.COMPATIBLE,
            catalog_source=ModelCatalogSource.LIVE,
            catalog_status=ModelCatalogStatus.AVAILABLE,
            candidate_count=1,
            model=model,
        )

    monkeypatch.setattr(streaming, "qualify_model", _qualify)
    monkeypatch.setattr(
        streaming, "retry_params", lambda: {"attempts": 1, "base_delay": 0, "max_delay": 0}
    )
    return spy_p, spy_s


@pytest.mark.asyncio
async def test_stream_failover_before_first_delta(monkeypatch):
    spy_p, spy_s = _patch_two_providers(
        monkeypatch,
        primary_behavior=lambda: (_ for _ in ()).throw(httpx.ConnectError("open fail")),
        secondary_behavior=lambda: _agen(["he", "llo"]),
    )
    out = [d async for d in _stream([{"role": "user", "content": "x"}], "m")]
    assert out == ["he", "llo"]
    assert spy_p == ["m"]  # primary пробован
    assert spy_s == ["model-p2"]  # secondary с переразрешённой моделью


@pytest.mark.asyncio
async def test_gigachat_schema_preflight_fails_over_without_http(monkeypatch):
    spy_p, spy_s = _patch_two_providers(
        monkeypatch,
        primary_behavior=lambda: _agen(["must-not-run"]),
        secondary_behavior=lambda: _agen(["fallback"]),
    )
    monkeypatch.setattr(streaming, "uses_legacy_functions", lambda name: name == "p1")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "dynamic_tool",
                "description": "Dynamic",
                "parameters": {"type": "object", "properties": {}, "$ref": "private"},
            },
        }
    ]
    state = ProviderRoundState()

    out = [
        delta
        async for delta in _stream(
            [{"role": "user", "content": "x"}], "m", tools=tools, round_state=state
        )
    ]

    assert out == ["fallback"]
    assert spy_p == []
    assert spy_s == ["model-p2"]
    assert state.provider_fallback_reason == "tool_schema"


@pytest.mark.asyncio
async def test_gigachat_schema_preflight_never_breaks_provider_pinning(monkeypatch):
    from service.domain.client.protocol.compiler import ProviderToolCompilationError

    spy_p, spy_s = _patch_two_providers(
        monkeypatch,
        primary_behavior=lambda: _agen(["must-not-run"]),
        secondary_behavior=lambda: _agen(["must-not-fallback"]),
    )
    monkeypatch.setattr(streaming, "uses_legacy_functions", lambda name: name == "p1")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "dynamic_tool",
                "description": "Dynamic",
                "parameters": {"type": "object", "properties": {}, "oneOf": []},
            },
        }
    ]

    with pytest.raises(ProviderToolCompilationError, match="tool_schema"):
        _ = [
            delta
            async for delta in _stream(
                [{"role": "user", "content": "x"}],
                "m",
                tools=tools,
                pin_provider="p1",
            )
        ]

    assert spy_p == []
    assert spy_s == []


@pytest.mark.asyncio
async def test_stream_failover_log_does_not_include_provider_body(monkeypatch):
    marker = "S22_PRIVATE_PROVIDER_RESPONSE"

    class _SensitiveProviderError(Exception):
        status_code = 500

    _patch_two_providers(
        monkeypatch,
        primary_behavior=lambda: (_ for _ in ()).throw(_SensitiveProviderError(marker)),
        secondary_behavior=lambda: _agen(["ok"]),
    )
    with patch.object(streaming.logger, "warning") as warning:
        out = [delta async for delta in _stream([{"role": "user", "content": "x"}], "m")]

    template, *args = warning.call_args.args
    rendered = template % tuple(args)
    assert out == ["ok"]
    assert marker not in rendered
    assert rendered.endswith("remote")
    assert "_SensitiveProviderError" not in rendered


@pytest.mark.asyncio
async def test_stream_no_failover_after_first_delta(monkeypatch):
    spy_p, spy_s = _patch_two_providers(
        monkeypatch,
        primary_behavior=lambda: _agen(["hi", "never"], raise_at=1),
        secondary_behavior=lambda: _agen(["should-not-run"]),
    )
    collected = []
    with pytest.raises(httpx.ConnectError):
        async for d in _stream([{"role": "user", "content": "x"}], "m"):
            collected.append(d)
    assert collected == ["hi"]  # успели отдать первую дельту
    assert spy_s == []  # secondary НЕ вызван — тихий свич запрещён


@pytest.mark.asyncio
async def test_stream_midstream_failure_trips_breaker(monkeypatch):
    """P1.3: провайдер, умерший НА СЕРЕДИНЕ стрима, должен быть выбит из primary.

    Раньше mark_down на mid-stream не звался (только фейловер-ветка до первой дельты),
    и «стримит-и-падает-на-токене-N» оставался первым на КАЖДЫЙ запрос, обрывая ответ
    снова и снова. Фейловер по-прежнему запрещён (тихий свич), но breaker обязан
    зафиксировать смерть.
    """
    from service.domain.client.resilience import circuit_breaker

    async def _timeout_midstream(chunks):
        # TimeoutError (builtin) распознаётся circuit_breaker.should_trip как падение
        # провайдера (в отличие от произвольной строки без транспорт-маркера).
        for i, c in enumerate(chunks):
            if i == 1:
                raise TimeoutError("provider timed out mid-stream")
            yield _Chunk(c)

    _patch_two_providers(
        monkeypatch,
        primary_behavior=lambda: _timeout_midstream(["hi", "boom"]),
        secondary_behavior=lambda: _agen(["nope"]),
    )
    collected = []
    with pytest.raises(TimeoutError):
        async for d in _stream([{"role": "user", "content": "x"}], "m"):
            collected.append(d)
    assert collected == ["hi"]
    assert "p1" in circuit_breaker._DOWN_UNTIL, "mid-stream смерть не выбила провайдера"


@pytest.mark.asyncio
async def test_failover_does_not_carry_failed_provider_usage(monkeypatch):
    """usage упавшего провайдера НЕ должен просочиться в следующего (мисатрибуция/недобилл).

    Сценарий-стык: A отдал usage-чанк (нестандартно — ДО контента) и упал до первой дельты;
    failover на B, который БЕЗ stream-usage (как mws/gigachat) генерит ответ без usage. Если
    usage_out не чистить между попытками, prompt/completion от A останутся и припишутся модели
    B, а вызывающий, увидев ненулевой usage, пропустит оценку по тексту → недобилл за реальную
    генерацию B. usage_out общий на весь фейловер, поэтому чистка обязана быть в цикле.
    """

    class _UsageChunk:
        def __init__(self, p, c):
            self.choices = []  # нет контента → дельта не йелдится, started=False → фейловер
            self.usage = type(
                "U", (), {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}
            )()

    async def _usage_then_fail():
        yield _UsageChunk(100, 0)  # A рапортует usage рано
        raise httpx.ConnectError("fail before first content delta")

    _patch_two_providers(
        monkeypatch,
        primary_behavior=_usage_then_fail,
        secondary_behavior=lambda: _agen(["real", "answer"]),  # B: контент без usage
    )
    state = ProviderRoundState()
    out = [d async for d in _stream([{"role": "user", "content": "x"}], "m", round_state=state)]
    assert out == ["real", "answer"], "ответ сгенерил B"
    assert state.provider == "p2", "обслужил B"
    assert not state.prompt, "usage упавшего A просочился в B (мисатрибуция/недобилл)"
    assert not state.completion, "usage упавшего A просочился в B"


# --------------------------------------------------------------------------- #
# create_chat_completion: гейт tools по провайдеру (non-stream)                 #
# --------------------------------------------------------------------------- #
def _patch_one_nonstream(monkeypatch, capture: dict):
    async def _create(*a, **k):
        capture.update(k)
        return "ok"

    module = type(
        "M", (), {"OPENAI_CLIENT": object(), "create_chat_completion": staticmethod(_create)}
    )()
    monkeypatch.setattr(chat, "build_provider_order", lambda _p: ["p1"])
    monkeypatch.setattr(chat, "get_provider_module", lambda n: module)

    async def _cat():
        return ([], {})

    monkeypatch.setattr(chat, "get_model_catalog", _cat)

    async def _identity(order):
        return order

    monkeypatch.setattr(chat.provider_policy, "drop_hard_off", _identity)

    async def _qualify(name, *, prefer=None, requirement=None, **_kwargs):
        return ModelQualification(
            provider=name,
            requirement=requirement or ModelRequirement(),
            status=ProviderQualificationStatus.COMPATIBLE,
            catalog_source=ModelCatalogSource.LIVE,
            catalog_status=ModelCatalogStatus.AVAILABLE,
            candidate_count=1,
            model=prefer,
        )

    monkeypatch.setattr(chat, "qualify_model", _qualify)
    monkeypatch.setattr(
        streaming, "retry_params", lambda: {"attempts": 1, "base_delay": 0, "max_delay": 0}
    )


@pytest.mark.asyncio
async def test_create_chat_excludes_model_when_tools_are_unsupported(monkeypatch):
    """Tool requirement excludes the model instead of silently removing grounding."""
    captured: dict = {}
    _patch_one_nonstream(monkeypatch, captured)

    async def _unsupported(name, *, prefer=None, requirement=None, **_kwargs):
        del prefer
        assert requirement is not None and requirement.tools is True
        return ModelQualification(
            provider=name,
            requirement=requirement,
            status=ProviderQualificationStatus.NO_COMPATIBLE_MODEL,
            catalog_source=ModelCatalogSource.LIVE,
            catalog_status=ModelCatalogStatus.AVAILABLE,
            candidate_count=0,
        )

    monkeypatch.setattr(chat, "qualify_model", _unsupported)

    with pytest.raises(ProviderProtocolError, match="no_compatible_model"):
        await chat.create_chat_completion(
            messages=[{"role": "user", "content": "x"}],
            model="giga:GigaChat",
            tools=[{"type": "function", "function": {"name": "f"}}],
            tool_choice="auto",
        )
    assert captured == {}, "incompatible provider must not receive a degraded request"


@pytest.mark.asyncio
async def test_create_chat_keeps_tools_when_supported(monkeypatch):
    captured: dict = {}
    _patch_one_nonstream(monkeypatch, captured)

    await chat.create_chat_completion(
        messages=[{"role": "user", "content": "x"}],
        model="openai/gpt-4o",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "f",
                    "description": "Test function",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            }
        ],
        tool_choice="auto",
    )
    assert captured.get("tools"), "у поддерживающей модели tools должны сохраниться"


@pytest.mark.asyncio
async def test_nonstream_provider_failure_log_does_not_echo_response_body(monkeypatch):
    marker = "S23_PRIVATE_PROVIDER_BODY"

    class _SensitiveError(Exception):
        status_code = 500

    async def _create(*_args, **_kwargs):
        raise _SensitiveError(marker)

    module = type(
        "M", (), {"OPENAI_CLIENT": object(), "create_chat_completion": staticmethod(_create)}
    )()
    monkeypatch.setattr(chat, "build_provider_order", lambda _provider: ["gigachat"])
    monkeypatch.setattr(chat, "get_provider_module", lambda _name: module)

    async def _catalog():
        return [], {}

    async def _identity(order):
        return order

    monkeypatch.setattr(chat, "get_model_catalog", _catalog)
    monkeypatch.setattr(chat.provider_policy, "drop_hard_off", _identity)
    monkeypatch.setattr(
        chat, "retry_params", lambda: {"attempts": 1, "base_delay": 0, "max_delay": 0}
    )

    with patch.object(chat.logger, "warning") as warning:
        with pytest.raises(_SensitiveError, match=marker):
            await chat.create_chat_completion(
                messages=[{"role": "user", "content": "synthetic"}], model="GigaChat-2"
            )

    template, *args = warning.call_args.args
    rendered = template % tuple(args)
    assert marker not in rendered
    assert rendered.endswith("remote")
    assert "_SensitiveError" not in rendered
