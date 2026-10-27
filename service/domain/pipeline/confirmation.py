"""A confirmation is a parked run, never implicit permission to spend."""

from datetime import UTC, datetime

from service.domain.routing.auto.decision import CONFIDENCE_HIGH
from service.events import AgentEvent, EventType
from service.settings import config
from service.shared.agent_settings import runtime_settings


def offer_ttl_sec() -> int:
    return max(
        5, int(runtime_settings.get_agents("mode_offer_ttl_sec", config.agents.mode_offer_ttl_sec))
    )


def waiting_event() -> AgentEvent:
    return AgentEvent(
        type=EventType.AGENT_COMPLETE,
        agent_name="router",
        data="",
        metadata={"awaiting_confirmation": True, "execution_status": "deferred"},
    )


def tool_offer_event(tool: str, label: str, reason_code: str, _user_input: str) -> AgentEvent:
    """One shared tool/mode decision card, with server deadline and no request text."""
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name="router",
        data=f"Предложено: {label}",
        metadata={
            "kind": "mode_offer",
            "mode_offer": {
                "offer_kind": "tool",
                "blocking": True,
                "mode": tool,
                "label": label,
                "reason_code": reason_code,
                "confidence": CONFIDENCE_HIGH,
                "offered_at": datetime.now(UTC).isoformat(),
                "expires_in_sec": offer_ttl_sec(),
            },
        },
    )
