"""No terminal envelope may erase/reprice committed ordered canonical calls."""

from copy import deepcopy
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.billing.usage.consistency import (
    require_terminal_usage,
)
from service.services.chat.infrastructure.chat_worker.billing.usage.journal import (
    JournalReceipt,
    UsageJournal,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable


def fixture():
    journal = UsageJournal(
        str(uuid4()),
        2,
        (
            JournalReceipt("first", "gigachat", "synthetic", "route_model", 2, 1, False),
            JournalReceipt("second", "openai", "synthetic", None, 4, 3, True),
        ),
    )
    result = {
        "prompt_tokens": 6,
        "completion_tokens": 4,
        "total_tokens": 10,
        "per_call_usage": [
            {
                "provider": r.provider,
                "model": r.model,
                "kind": r.kind,
                "prompt": r.prompt,
                "completion": r.completion,
                "estimated": r.estimated,
            }
            for r in journal.receipts
        ],
    }
    return journal, result


def test_exact_projection_is_read_only_and_repeatable():
    journal, result = fixture()
    original = deepcopy(result)
    require_terminal_usage(result, journal)
    require_terminal_usage(result, journal)
    assert result == original and len(journal.receipts) == 2


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "reordered",
        "merged",
        "provider",
        "model",
        "kind",
        "precision",
        "count",
        "boolean",
        "total",
        "extra",
        "raw",
    ],
)
def test_mismatch_fails_closed_without_diagnostics_payload(fault):
    journal, result = fixture()
    calls = result["per_call_usage"]
    if fault == "missing":
        result.pop("per_call_usage")
    elif fault == "reordered":
        calls.reverse()
    elif fault == "merged":
        calls.pop()
    elif fault in {"provider", "model", "kind"}:
        calls[0][fault] = "PRIVATE_EXCEPTION_MARKER"
    elif fault == "precision":
        calls[1]["estimated"] = False
    elif fault == "count":
        calls[0]["prompt"] = 3
    elif fault == "boolean":
        calls[0]["completion"] = True
    elif fault == "total":
        result["total_tokens"] = 999
    elif fault == "extra":
        calls.append(dict(calls[0]))
    else:
        calls[0] = "PRIVATE_EXCEPTION_MARKER"
    with pytest.raises(JobStateUnavailable) as error:
        require_terminal_usage(result, journal)
    assert str(error.value) == "Usage checkpoint mismatch"


def test_legacy_without_private_checkpoint_keeps_existing_contract():
    require_terminal_usage({}, None)


def test_missing_provenance_is_not_dropped_and_absent_estimate_means_exact():
    journal = UsageJournal(
        str(uuid4()), 1, (JournalReceipt("call", None, None, None, 2, 1, False),)
    )
    require_terminal_usage(
        {
            "prompt_tokens": 2,
            "completion_tokens": 1,
            "total_tokens": 3,
            "per_call_usage": [{"model": None, "prompt": 2, "completion": 1}],
        },
        journal,
    )
