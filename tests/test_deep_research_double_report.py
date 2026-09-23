"""LDR deep_research: сбой пост-обработки метрик НЕ должен плодить второй отчёт.

Регрессия (CRITICAL, двойной биллинг): отчёт LDR стримится пользователю, ПОСЛЕ чего
идёт отдельный вызов client.metrics(). Если он падал, исключение всплывало в
process()→except → used_ldr оставался False → запускался нативный путь, и
пользователь получал ДВА отчёта (LDR + нативный), оба тарифицировались.
"""

from types import SimpleNamespace

import pytest

from service.domain import client as client_mod
from service.domain.subagents import deep_research as dr_mod
from service.infrastructure.integration import ldr_research as ldr_mod


class _FakeLDRClient:
    available = True
    model = "ldr-model"

    def __init__(self, *a, **k):
        # Двойник ведёт это состояние как настоящий клиент: по нему слой отмены
        # решает, слать ли `POST /api/terminate`.
        self.active_research_id = None
        self.terminated = []

    async def start_research(self, topic):
        self.active_research_id = "rid"
        return "rid"

    async def terminate(self):
        self.terminated.append(self.active_research_id)
        self.active_research_id = None
        return True

    async def iter_status(self, rid):
        for _ in []:  # пустой async-генератор (без статус-апдейтов)
            yield _

    async def report(self, rid):
        self.active_research_id = None  # как в настоящем клиенте: отчёт = штатное завершение
        return {"summary": "Отчёт по теме исследования на русском.", "sources": []}

    async def metrics(self, rid):
        raise RuntimeError("metrics service down")  # падает ПОСЛЕ отдачи отчёта

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_ldr_metrics_failure_does_not_trigger_native_double_report(monkeypatch) -> None:
    monkeypatch.setattr(ldr_mod, "LDRResearchClient", _FakeLDRClient)
    monkeypatch.setattr(dr_mod.DeepResearchAgent, "_resolve_provider", staticmethod(lambda: "ldr"))

    async def _no_models():
        return []

    monkeypatch.setattr(client_mod, "list_available_models", _no_models)

    # Нативный путь помечаем маркером — если он запустится, это двойной отчёт.
    async def _native_marker(self, *a, **k):
        yield self.error_event("NATIVE_RAN")

    monkeypatch.setattr(dr_mod.DeepResearchAgent, "_run_native", _native_marker)

    agent = dr_mod.DeepResearchAgent(model_settings={})

    async def _safe(_text):
        return {"blocked": False, "sensitive": False, "meta": {}, "message": None}

    monkeypatch.setattr(agent, "evaluate_input_safety", _safe)

    context = SimpleNamespace(history_messages=[])
    events = [e async for e in agent.process("исследуй тему", context=context)]
    texts = "".join(str(getattr(e, "data", "") or "") for e in events)

    assert "Отчёт по теме исследования" in texts  # отчёт LDR отдан
    assert "NATIVE_RAN" not in texts  # нативный путь НЕ запускался → нет двойного отчёта
