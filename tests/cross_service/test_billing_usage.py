"""Фаза 1 биллинга: захват потребления токенов (read-only учёт).

Покрывает цепочку ДО границы сервиса: client → usage_tracking._extract_usage → ReplyAssembler →
execution_result. Дальше числа уезжают в backend, и там же осталась их запись в БД:
``BillingRepository.record_usage_event`` проверял SQL-текст INSERT'а и коммит — движок в
этом не участвует, фейк проверял бы сам себя. Тест остался в backend'е.

Здесь, стало быть, доказывается только одна половина — что движок отдаёт ПРАВИЛЬНЫЕ
числа. Что backend их правильно записывает — уже не здесь.
"""

from types import SimpleNamespace

import pytest

from service.application.reply_assembler import ReplyAssembler
from service.application.use_cases.agent_execution_use_cases import (
    PersistSessionHistoryUseCase,
)

# ⚠️ `_extract_usage` живёт в `service.domain.usage_tracking`, а не в `base`. Раньше он
# был виден и через `base` — как побочный эффект импорта; после разделения `base.py` на
# пути исполнения импорт оттуда ушёл, и тест это вскрыл. Ссылаемся на настоящий дом.
from service.domain import usage_tracking as base
from service.events import EventType


# --------------------------------------------------------------------------- #
# usage_tracking._extract_usage                                                          #
# --------------------------------------------------------------------------- #
def test_extract_usage_reads_openai_shape() -> None:
    resp = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14)
    )
    assert base._extract_usage(resp) == {"prompt": 10, "completion": 4, "total": 14}


def test_extract_usage_derives_total_when_absent() -> None:
    resp = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4))
    assert base._extract_usage(resp) == {"prompt": 10, "completion": 4, "total": 14}


def test_extract_usage_empty_when_missing_or_zero() -> None:
    assert base._extract_usage(SimpleNamespace()) == {}
    assert base._extract_usage(SimpleNamespace(usage=None)) == {}
    assert (
        base._extract_usage(
            SimpleNamespace(usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0))
        )
        == {}
    )


# --------------------------------------------------------------------------- #
# ReplyAssembler accumulation                                                  #
# --------------------------------------------------------------------------- #
def _event(type_, data=None, metadata=None):
    return SimpleNamespace(type=type_, data=data, metadata=metadata)


def _consume(assembler, event):
    assembler.consume(
        event=event,
        stream_chunk_type=EventType.STREAM_CHUNK,
        error_type=EventType.ERROR,
        structured_output_type=EventType.STRUCTURED_OUTPUT,
    )


def test_reply_assembler_accumulates_usage_across_calls() -> None:
    asm = ReplyAssembler()
    _consume(asm, _event(EventType.STREAM_CHUNK, data="Привет", metadata={"model": "m1"}))
    _consume(
        asm,
        _event(
            EventType.AGENT_COMPLETE,
            metadata={
                "model": "m1",
                "token_usage": {"prompt": 100, "completion": 50, "total": 150, "model": "m1"},
            },
        ),
    )
    # второй вызов (например, мультимодальный fan-out) суммируется
    _consume(
        asm,
        _event(
            EventType.AGENT_COMPLETE,
            metadata={"token_usage": {"prompt": 10, "completion": 5, "total": 15, "model": "m2"}},
        ),
    )

    assert asm.prompt_tokens == 110
    assert asm.completion_tokens == 55
    assert asm.total_tokens == 165
    assert len(asm.per_call_usage) == 2
    assert asm.per_call_usage[0] == {"model": "m1", "prompt": 100, "completion": 50}


def test_reply_assembler_keeps_actual_provider_for_pricing() -> None:
    asm = ReplyAssembler()
    _consume(
        asm,
        _event(
            EventType.AGENT_COMPLETE,
            metadata={
                "token_usage": {
                    "model": "openai/gpt-4o-mini",
                    "provider": "routerai",
                    "prompt": 100,
                    "completion": 50,
                }
            },
        ),
    )
    assert asm.per_call_usage == [
        {
            "model": "openai/gpt-4o-mini",
            "provider": "routerai",
            "prompt": 100,
            "completion": 50,
        }
    ]


def test_reply_assembler_keeps_token_usage_internal() -> None:
    """token_usage не должен просачиваться в наружную metadata ответа."""
    asm = ReplyAssembler()
    _consume(
        asm,
        _event(
            EventType.AGENT_COMPLETE,
            metadata={"model": "m1", "token_usage": {"prompt": 7, "completion": 3}},
        ),
    )
    assert "token_usage" not in asm.metadata
    assert asm.metadata.get("model") == "m1"
    assert asm.prompt_tokens == 7


def test_reply_assembler_ignores_malformed_usage() -> None:
    asm = ReplyAssembler()
    _consume(asm, _event(EventType.AGENT_COMPLETE, metadata={"token_usage": "nope"}))
    _consume(asm, _event(EventType.AGENT_COMPLETE, metadata={"token_usage": {"prompt": 0}}))
    assert asm.total_tokens == 0
    assert asm.per_call_usage == []


# --------------------------------------------------------------------------- #
# execution_result surfacing                                                   #
# --------------------------------------------------------------------------- #
def test_persist_session_history_surfaces_tokens() -> None:
    asm = ReplyAssembler()
    asm.reply_parts = ["hello"]
    asm.prompt_tokens = 120
    asm.completion_tokens = 30
    asm.per_call_usage = [{"model": "m", "prompt": 120, "completion": 30}]

    result = PersistSessionHistoryUseCase().execute(
        reply="hello",
        metadata={"model_routing": {}},
        resolved_model="m",
        reply_assembler=asm,
    )

    assert result["prompt_tokens"] == 120
    assert result["completion_tokens"] == 30
    assert result["total_tokens"] == 150
    assert result["per_call_usage"] == [{"model": "m", "prompt": 120, "completion": 30}]


# --------------------------------------------------------------------------- #
# client.stream_chat_completion usage capture                                  #
# --------------------------------------------------------------------------- #
class _FakeChunk:
    def __init__(self, content=None, usage=None):
        self.choices = (
            [SimpleNamespace(delta=SimpleNamespace(content=content))] if content is not None else []
        )
        self.usage = usage


def _fake_client(chunks, captured):
    class FakeCompletions:
        async def create(self, **payload):
            captured.update(payload)

            async def agen():
                for chunk in chunks:
                    yield chunk

            return agen()

    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))


async def _isolate_provider_order(monkeypatch, client_mod, provider: str) -> None:
    """Изолировать стрим от ЖИВОГО здоровья провайдеров.

    ``stream_chat_completion`` берёт запатченный тестом клиент только для
    ``ACTIVE_PROVIDER``, а порядок провайдеров перед этим прогоняется через
    ``drop_hard_off``/``_drop_cooled_down``. Если провайдер выключен политикой или
    выбит breaker'ом в этом окружении (например, исчерпан ключ), он из очереди
    выпадает — и тест уходил к СОСЕДНЕМУ провайдеру с настоящим клиентом, делая
    реальный платный вызов вместо проверки учёта токенов. Здесь фильтры снимаем:
    тест про usage, а не про здоровье стенда.
    """
    # ⚠️ Каждое имя патчится ТАМ, ГДЕ ЕГО ЧИТАЮТ. Активный провайдер живёт в `active`
    # (его меняет пересборка после смены ключа), порядок и breaker — в `streaming`.
    # Патч «по фасаду пакета» после разделения модулей не доходит ни до кого.
    from service.domain.client import active
    from service.domain.client.resilience import circuit_breaker

    monkeypatch.setattr(active, "ACTIVE_PROVIDER", provider)
    monkeypatch.setattr(client_mod, "build_provider_order", lambda _active: [provider])
    monkeypatch.setattr(client_mod.provider_policy, "drop_hard_off", _passthrough)
    monkeypatch.setattr(circuit_breaker, "drop_cooled_down_local", lambda order: list(order))

    async def _qualify(_name, *, prefer=None, requirement=None, **_kwargs):
        from service.domain.client.model_catalog import ModelCatalogSource, ModelCatalogStatus
        from service.domain.client.model_requirements import (
            ModelQualification,
            ModelRequirement,
            ProviderQualificationStatus,
        )

        return ModelQualification(
            provider=provider,
            requirement=requirement or ModelRequirement.CHAT,
            status=ProviderQualificationStatus.COMPATIBLE,
            catalog_source=ModelCatalogSource.LIVE,
            catalog_status=ModelCatalogStatus.AVAILABLE,
            candidate_count=1,
            model=prefer,
        )

    monkeypatch.setattr(client_mod, "qualify_model", _qualify)


async def _passthrough(order):
    return list(order)


@pytest.mark.asyncio
async def test_stream_chat_completion_captures_usage(monkeypatch) -> None:
    # ⚠️ Модуль-ВЛАДЕЛЕЦ стрима, а не фасад пакета: патч по `service.domain.client`
    # после разделения до `streaming.py` не доходит.
    from service.domain.client.calls import legacy_stream as client_mod
    from service.domain.client.calls import streaming as stream_owner

    captured: dict = {}
    chunks = [
        _FakeChunk(content="Привет"),
        _FakeChunk(content=" мир"),
        _FakeChunk(
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30, total_tokens=150)
        ),
    ]
    from service.domain.client import active as _active

    monkeypatch.setattr(_active, "get_openai_client", lambda: _fake_client(chunks, captured))
    await _isolate_provider_order(monkeypatch, stream_owner, "openrouter")

    usage_out: dict = {}
    collected = []
    async for delta in client_mod.stream_chat_completion(
        messages=[{"role": "user", "content": "x"}], model="m", usage_out=usage_out
    ):
        collected.append(delta)

    assert "".join(collected) == "Привет мир"
    assert captured.get("stream_options") == {"include_usage": True}
    # Учёт токенов — то, ради чего тест. usage_out несёт и служебные поля транспорта
    # (provider — чтобы tool-loop приколотил все раунды к одному провайдеру), поэтому
    # сверяем сами метрики, а не весь словарь целиком.
    assert {k: usage_out[k] for k in ("prompt", "completion", "total", "model")} == {
        "prompt": 120,
        "completion": 30,
        "total": 150,
        "model": "m",
    }
    assert usage_out["provider"] == "openrouter"


@pytest.mark.asyncio
async def test_stream_chat_completion_skips_usage_for_mws(monkeypatch) -> None:
    """MWS может не понимать stream_options — не запрашиваем usage, не ломаем стрим."""
    # ⚠️ Модуль-ВЛАДЕЛЕЦ стрима, а не фасад пакета: патч по `service.domain.client`
    # после разделения до `streaming.py` не доходит.
    from service.domain.client.calls import legacy_stream as client_mod
    from service.domain.client.calls import streaming as stream_owner

    captured: dict = {}
    chunks = [_FakeChunk(content="ok")]
    from service.domain.client import active as _active

    monkeypatch.setattr(_active, "get_openai_client", lambda: _fake_client(chunks, captured))
    await _isolate_provider_order(monkeypatch, stream_owner, "mws")

    usage_out: dict = {}
    collected = [
        d
        async for d in client_mod.stream_chat_completion(
            messages=[{"role": "user", "content": "x"}], model="m", usage_out=usage_out
        )
    ]

    assert collected == ["ok"]
    assert "stream_options" not in captured
    # Суть теста: у MWS токены НЕ захватываются (он не понимает stream_options).
    # Служебные поля транспорта (provider/model) при этом пишутся всегда.
    assert not any(k in usage_out for k in ("prompt", "completion", "total"))
