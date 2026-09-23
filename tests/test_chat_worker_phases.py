from __future__ import annotations

import pytest

from service.services.chat.infrastructure.chat_worker.phases import (
    RunPhase,
    RunPhaseState,
    RunPhaseViolation,
)


def test_worker_run_phase_requires_exact_order() -> None:
    state = RunPhaseState()
    for phase in (
        RunPhase.RESERVED,
        RunPhase.EXECUTING,
        RunPhase.RESULT_LATCHED,
        RunPhase.CHARGED,
        RunPhase.PERSISTED,
    ):
        state.advance(phase)
    state.mark_publication(True)
    state.advance(RunPhase.FINALIZED)

    assert state.finalized is True
    assert state.publication_delivered is True


def test_worker_run_phase_rejects_skips_and_reentry() -> None:
    state = RunPhaseState()

    with pytest.raises(RunPhaseViolation, match="invalid_worker_phase_transition"):
        state.advance(RunPhase.EXECUTING)

    state.advance(RunPhase.RESERVED)
    with pytest.raises(RunPhaseViolation, match="invalid_worker_phase_transition"):
        state.advance(RunPhase.RESERVED)


def test_publication_stage_tracks_best_effort_transport_outcome() -> None:
    state = RunPhaseState()
    for phase in (
        RunPhase.RESERVED,
        RunPhase.EXECUTING,
        RunPhase.RESULT_LATCHED,
        RunPhase.CHARGED,
        RunPhase.PERSISTED,
    ):
        state.advance(phase)

    state.mark_publication(False)

    assert state.phase is RunPhase.PUBLISHED
    assert state.publication_delivered is False
