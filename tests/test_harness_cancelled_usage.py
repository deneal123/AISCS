"""Отмена после восстановления не теряет usage предыдущего attempt и не гадает о расходе."""

from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.harness.cancelled_usage import canonical_usage


def grant(**changes):
    result = {
        "operation_id": uuid4(),
        "state": "succeeded",
        "request": {"provider": "gigachat", "model": "test-model", "kind": "chat"},
        "receipt": {"prompt": 2, "completion": 1, "estimated": False},
    }
    result.update(changes)
    return result


def test_restore_uses_backend_receipts_even_without_current_attempt_journal():
    attempt = str(uuid4())
    paid = grant()
    journal = canonical_usage(attempt, None, [paid])
    assert journal.attempt_id == attempt and journal.revision == 1
    assert journal.receipts[0].receipt_id == str(paid["operation_id"])
    assert journal.receipts[0].prompt == 2 and journal.receipts[0].completion == 1
    assert not journal.receipts[0].estimated
    assert canonical_usage(attempt, journal.payload(), [paid]) == journal


def test_append_missing_confirmed_receipt_does_not_drop_existing_usage():
    attempt = str(uuid4())
    first, second = grant(), grant()
    previous = canonical_usage(attempt, None, [first])
    result = canonical_usage(attempt, previous.payload(), [first, second])
    assert result.extends(previous) and result.revision == 2
    assert len(result.receipts) == 2


@pytest.mark.parametrize("state", ["unknown", "dispatched"])
def test_unknown_cost_is_never_turned_into_zero_usage(state):
    with pytest.raises(JobStateUnavailable, match="cost unknown"):
        canonical_usage(str(uuid4()), None, [grant(state=state)])


def test_unmatched_or_reordered_canonical_receipts_fail_closed():
    attempt = str(uuid4())
    first, second = grant(), grant()
    previous = canonical_usage(attempt, None, [first, second])
    with pytest.raises(JobStateUnavailable, match="mismatch"):
        canonical_usage(attempt, previous.payload(), [second, first])


def test_tool_fee_or_unexecuted_allocation_is_not_a_model_usage_receipt():
    fee = grant(request={"billing_tool": "workspace_tool"})
    with pytest.raises(JobStateUnavailable, match="usage unavailable"):
        canonical_usage(str(uuid4()), None, [fee, grant(state="waived"), grant(state="allocated")])
