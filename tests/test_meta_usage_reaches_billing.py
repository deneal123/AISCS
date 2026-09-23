"""Служебные токены доезжают до СОБЫТИЯ, а не просто до накопителя.

⚠️ ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ, КОГДА ЕСТЬ test_service_call_billing. Тот проверяет, что
`compress_to_budget` заполняет `usage_out`, и что фабрика этот накопитель проносит.
Обе проверки — про ФУНКЦИЮ. Между «накопитель заполнен» и «пользователю выставлен
счёт» лежит место вызова, и именно там деньги терялись: событие с `token_usage`
собиралось из `meta_usage` ДО сборки контекста, а сжатие досыпало туда токены ПОСЛЕ.
Словарь был уже сериализован — до биллинга эти токены не доезжали никогда.

Сжатие — самый дорогой служебный вызов из всех: до 12 map + reduce НА СЕКЦИЮ, и
сжимаемых секций три. То есть терялось ровно то, что дороже всего, и ровно на самых
тяжёлых запросах — с крупным вложением.
"""

from __future__ import annotations

import pytest

from service.application.processor import AgentProcessor
from service.domain.pipeline import context_assembler as ca
from service.events import AgentEvent, EventType


class _Capturing:
    name = "general"

    async def process(self, user_input, context):
        yield AgentEvent(type=EventType.STREAM_CHUNK, agent_name="general", data="OK")


def _token_usages(events: list[AgentEvent]) -> list[dict]:
    return [
        e.metadata["token_usage"] for e in events if e.metadata and e.metadata.get("token_usage")
    ]


@pytest.mark.asyncio
async def test_compression_tokens_reach_a_billing_event(monkeypatch):
    """Сжатие контекста тарифицируется, а не выполняется за счёт платформы."""

    def _fake_make_compressor(config, *, execution):
        async def _compressor(raw, target, kind):
            from service.domain.usage_ledger import UsageKind

            execution.usage.record_usage(
                {"prompt": 500, "completion": 120},
                provider="synthetic",
                model="compressor/model",
                kind=UsageKind.META,
            )
            return "сжатая выжимка"

        return _compressor

    monkeypatch.setattr(
        "service.application.processor_steps.make_compressor", _fake_make_compressor
    )

    # Крошечный бюджет — чтобы вложение гарантированно пошло в сжатие.
    async def _tiny_budget(**_kw):
        from service.domain.pipeline.context_budget import ContextBudget

        return ContextBudget(
            window=4000,
            usable=600,
            output_reserve=0,
            prompt_overhead=0,
            sections={"files": 200},
        )

    monkeypatch.setattr(ca, "compute_budget", _tiny_budget)

    processor = AgentProcessor()
    processor.orchestrator._agents["general"] = _Capturing()

    events = [
        e
        async for e in processor.process_message_stream(
            "проанализируй вложение",
            "t-compress",
            user_id=None,
            session=None,
            input_type="image",  # форсит general без LLM-роутинга
            file_context="огромный документ " * 3000,
        )
    ]

    billed = sum(u.get("completion", 0) for u in _token_usages(events))
    assert billed >= 120, (
        f"токены сжатия до биллинга не доехали (учтено completion={billed}) — "
        "платформа заплатила провайдеру, пользователю счёт не выставлен"
    )


@pytest.mark.asyncio
async def test_no_meta_usage_event_when_nothing_was_spent(monkeypatch):
    """⚠️ Обратная сторона: пустой служебный счёт НЕ порождает событие.

    Без этого можно было бы «починить» потерю, отправляя нулевой token_usage всегда —
    тест выше остался бы зелёным, а в трейсе появился бы мусор на каждом ответе.
    """

    def _no_compression(config, *, execution):
        return None

    monkeypatch.setattr("service.application.processor_steps.make_compressor", _no_compression)

    processor = AgentProcessor()
    processor.orchestrator._agents["general"] = _Capturing()

    events = [
        e
        async for e in processor.process_message_stream(
            "короткий вопрос",
            "t-empty",
            user_id=None,
            session=None,
            input_type="image",
        )
    ]

    meta = [e for e in events if e.metadata and e.metadata.get("kind") == "meta_usage"]
    assert meta == [], "нулевой служебный usage отправлен событием"
