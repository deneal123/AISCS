"""AgentEvent.metadata: None коерсится в {} перед валидацией.

Регрессия: metadata объявлена как обязательный dict, но complete_event(msg) без
метаданных (и _usage_meta(...)→None на путях без usage) передавал metadata=None →
pydantic ValidationError → падал весь субагент на завершающем событии
(pure-transcribe, guardrail-block, image-fallback, «нет моделей»).
"""

from service.events import AgentEvent, EventType


def test_agent_event_metadata_none_coerced_to_dict() -> None:
    ev = AgentEvent(type=EventType.AGENT_COMPLETE, agent_name="x", data="done", metadata=None)
    assert ev.metadata == {}


def test_agent_event_metadata_dict_preserved() -> None:
    ev = AgentEvent(type=EventType.AGENT_COMPLETE, data="done", metadata={"token_usage": {"a": 1}})
    assert ev.metadata == {"token_usage": {"a": 1}}


def test_complete_event_without_metadata_does_not_raise() -> None:
    from service.domain.subagents.audio_transcribe import AudioTranscriptionAgent

    agent = AudioTranscriptionAgent(model_settings={})
    ev = agent.complete_event("done")  # metadata=None по умолчанию — не должно падать
    assert ev.type == EventType.AGENT_COMPLETE
    assert ev.metadata == {}
