"""PG-проверка scope/version: синтетическое evidence, без модели и команд."""

import os

import pytest

from tests.harness_postgres import run_probe


@pytest.mark.skipif(os.getenv("HARNESS_RUNTIME_LIVE") != "1", reason="Изолированный PG opt-in")
def test_ui_write_invalidates_bound_read_without_any_command():
    assert run_probe(
        "read_invalidation_probe",
        [
            "service/shared/harness_protocol.py",
            "service/services/chat/persistence/harness/commands/invalidation.py",
            "service/services/chat/persistence/harness/state.py",
            "service/services/chat/persistence/harness/admission/workspace_scope.py",
        ],
    ) == {
        "cases": [
            "wrong_workspace_unchanged",
            "read_without_command_invalidated",
            "terminal_history_unchanged",
            "parked_question_read_invalidated",
            "expired_question_history_unchanged",
            "accepted_child_read_invalidated",
            "terminal_child_history_unchanged",
            "foreign_question_scope_unchanged",
            "legacy_binding_invalidates_unobserved_evidence",
        ],
        "fixture_removed": True,
        "source_parity": True,
    }
