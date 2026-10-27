"""Устаревшая проекция сайдкара не подтверждает проверку новой версии проекта."""

from copy import deepcopy

import pytest

from service.services.chat.infrastructure.chat_worker.harness.finalization import (
    UNVERIFIED_REPLY,
    merge_projection,
    missing_contract_projection,
    protect_displayed_reply,
)
from service.shared.task_contract import CompletionVerifier
from tests.test_task_contract import evidence, state


def completed():
    return CompletionVerifier.evaluate(state(evidence=[evidence(), evidence("test")]))


def test_stale_confirmed_criteria_are_replaced_without_losing_binding_blocker():
    old = completed()
    old.update(status="blocked", verified=False, blocker="binding_changed")
    before = deepcopy(old)
    current = CompletionVerifier.evaluate(
        state(source_revision="r2", evidence=[evidence(), evidence("test")])
    )
    result = merge_projection(current, old)
    assert result["status"] == "blocked" and result["blocker"] == "binding_changed"
    assert result["unchecked"] == ["source", "test"] and result["confirmed"] == []
    assert result["references"] == [] and old == before


@pytest.mark.parametrize("reason", ["cost_unknown", "operation_unknown", "cancelled"])
def test_reported_blocker_does_not_hide_unknown_cost_effect_or_server_stop(reason):
    reported = completed()
    reported.update(status="blocked", verified=False, blocker="binding_changed")
    backend = completed()
    backend.update(
        status="cancelled" if reason == "cancelled" else "blocked", verified=False, blocker=reason
    )
    assert merge_projection(backend, reported)["blocker"] == reason


def test_backend_evidence_does_not_upgrade_executor_stop_into_success():
    reported = completed()
    reported.update(status="blocked", verified=False, blocker="round_limit")
    result = merge_projection(completed(), reported)
    assert result["status"] == "blocked" and result["blocker"] == "round_limit"


def test_reported_completed_does_not_override_current_backend_failure():
    backend = CompletionVerifier.evaluate(state())
    assert merge_projection(backend, completed()) == backend


@pytest.mark.parametrize(
    "reported", [None, completed(), {"schema_version": 1, "status": "completed"}]
)
def test_unsealed_backend_contract_cannot_be_completed_by_sidecar_projection(reported):
    result = missing_contract_projection(reported)
    assert not result["verified"] and result["status"] == "blocked"
    assert result["confirmed"] == [] and result["unchecked"] == ["contract"]


def test_unsealed_user_question_retains_waiting_state_not_fake_success():
    reported = missing_contract_projection(None)
    reported.update(status="waiting_user", blocker="user_decision_required")
    assert missing_contract_projection(reported) == reported


def test_unverified_display_replaces_false_success_but_keeps_canonical_terminal():
    from service.services.chat.infrastructure.chat_worker.results.prepared import (
        _displayed_reply,
        _reply_projection,
    )

    canonical = "Готово, всё проверено."
    old = {"task_result": completed()}
    new = {"task_result": CompletionVerifier.evaluate(state())}
    displayed = protect_displayed_reply(canonical, old, new)
    assert displayed == UNVERIFIED_REPLY
    projection = _reply_projection(canonical, displayed, new)
    assert projection == "harness_unverified"
    assert _displayed_reply(canonical, new, {"reply_projection": projection}) == displayed
    assert canonical == "Готово, всё проверено."
    assert protect_displayed_reply(canonical, old, old) == canonical
    assert protect_displayed_reply("Частичный ответ", new, new) == "Частичный ответ"
