"""Private inputs and outcomes of application routing stages, not the /route wire."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from service.events import AgentEvent
from service.schemas.agents import ModalityAttachment


@dataclass(frozen=True)
class RouteDecision:
    """Кто и как отвечает на этот запрос — итог фазы маршрутизации.

    Именованные поля, а не кортеж из пяти: ``subtasks`` и ``multimodal`` независимы
    (мульти-интент и вложения ортогональны), и путать их местами при распаковке —
    ровно тот класс ошибки, из-за которого декомпозиция когда-то молча отменялась
    любыми двумя вложениями.
    """

    agent_name: str
    subtasks: list | None
    plan_context: str | None
    # Контекст вложений: свой + агрегированный fan-out'ом, если он был.
    file_context: str
    multimodal: bool
    # Не сериализуется в trace: это уже отобранный внутренний каталогом сценарий.
    catalog_workflow: Any | None = None
    context_updates: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class RouteInputs:
    user_input: str
    route_override: str | None = None
    resolved_category: str | None = None
    input_type: str | None = None
    web_search: bool = False
    deep_research: bool = False
    multi_intent: bool | None = None
    planning: bool | None = None
    file_context: str | None = None
    attachments: list | None = None
    context: Any = None
    history_messages: list[dict] | None = None
    compact_summary: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class RoutePreparation:
    """Prepared policy inputs or a parked confirmation; never task completion."""

    attachments: list[ModalityAttachment] = field(default_factory=list)
    multimodal: bool = False
    multi_intent: bool | None = None
    planning: bool | None = None
    resolved_category: str | None = None
    force_decompose: bool = False
    events: list[AgentEvent] = field(default_factory=list)
    parked: RouteDecision | None = None
