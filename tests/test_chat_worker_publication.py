from __future__ import annotations

import pytest

from service.services.chat.infrastructure.chat_worker.phases import RunPhase, RunPhaseState
from service.services.chat.infrastructure.chat_worker.publication import publish_committed_turn


class _Publisher:
    def __init__(self, outcome=True) -> None:
        self.outcome = outcome
        self.payloads: list[dict] = []

    def publish_payload(self, payload: dict):
        self.payloads.append(payload)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _persisted_phase() -> RunPhaseState:
    state = RunPhaseState()
    for phase in (
        RunPhase.RESERVED,
        RunPhase.EXECUTING,
        RunPhase.RESULT_LATCHED,
        RunPhase.CHARGED,
        RunPhase.PERSISTED,
    ):
        state.advance(phase)
    return state


@pytest.mark.asyncio
async def test_post_commit_publication_runs_memory_after_reply() -> None:
    publisher = _Publisher()
    calls: list[dict] = []

    async def extract_memory(**kwargs) -> None:
        calls.append(kwargs)

    phase = _persisted_phase()
    await publish_committed_turn(
        publisher=publisher,
        job_id="job",
        reply="answer",
        file_url=None,
        metadata={"selected_model": "model"},
        run_phase=phase,
        memory_enabled=True,
        extract_memory=extract_memory,
        memory_kwargs={"bounded": True},
    )

    assert publisher.payloads[0]["type"] == "agent_reply"
    assert calls == [{"bounded": True}]
    assert phase.finalized is True
    assert phase.publication_delivered is True


@pytest.mark.asyncio
async def test_post_commit_transport_failure_is_finalized_without_memory() -> None:
    marker = "private-provider-body"
    calls = 0

    async def extract_memory(**_kwargs) -> None:
        nonlocal calls
        calls += 1

    phase = _persisted_phase()
    await publish_committed_turn(
        publisher=_Publisher(RuntimeError(marker)),
        job_id="job",
        reply="answer",
        file_url=None,
        metadata={},
        run_phase=phase,
        memory_enabled=True,
        extract_memory=extract_memory,
        memory_kwargs={},
    )

    assert calls == 0
    assert phase.finalized is True
    assert phase.publication_delivered is False
