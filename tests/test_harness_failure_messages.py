"""Причина остановки — закрытая проекция, не текст исключения или обещание retry."""

import pytest

from service.application.harness.messages import failure_message
from service.application.harness.result import failure_reply
from service.domain.execution.context import PrivateRunResources, use_run_execution


@pytest.mark.parametrize(
    "code,fragment",
    [
        ("operation_unknown", "Автоматический повтор заблокирован"),
        ("cost_unknown", "ещё уточняется"),
        ("task_contract_invalid", "проверяемые критерии"),
        ("binding_changed", "по прежней версии"),
        ("budget_exhausted", "увеличение бюджета не выполняется"),
    ],
)
def test_known_blocker_is_actionable_without_claiming_success_or_no_spend(code, fragment):
    with use_run_execution(PrivateRunResources()) as execution:
        result = failure_reply(execution, code, "test-model")
    assert fragment in result["reply"]
    assert result["metadata"]["task_result"]["blocker"] == code
    assert result["metadata"]["task_result"]["verified"] is False


def test_unknown_exception_text_is_never_used_as_a_message():
    assert "PRIVATE_TOKEN" not in failure_message("PRIVATE_TOKEN")
