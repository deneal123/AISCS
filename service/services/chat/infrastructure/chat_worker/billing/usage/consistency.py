"""Terminal accounting must agree with the last committed canonical checkpoint."""

from typing import Any

from service.services.chat.infrastructure.chat_worker.billing.usage.journal import UsageJournal
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.jobs.persistence.transitions import EXECUTION_KEY, USAGE_JOURNAL_KEY


def require_stored_usage(result: dict[str, Any], payload: dict[str, Any]) -> None:
    """Apply the same invariant on redelivery before artifact recovery or charging."""
    if USAGE_JOURNAL_KEY not in payload:
        return
    journal = UsageJournal.decode(payload[USAGE_JOURNAL_KEY])
    if journal.attempt_id != payload.get(EXECUTION_KEY):
        raise JobStateUnavailable("Usage checkpoint mismatch")
    require_terminal_usage(result, journal)


def require_terminal_usage(result: dict[str, Any], journal: UsageJournal | None) -> None:
    """Validate the historical wire projection without creating/merging receipts.

    The public envelope does not carry receipt IDs. Compare every ordered call,
    its provenance, precision and totals; never infer missing calls from totals.
    A legacy run without a private checkpoint keeps its existing terminal path.
    """
    if journal is None:
        return
    try:
        calls = result.get("per_call_usage")
        if not isinstance(calls, list) or len(calls) != len(journal.receipts):
            raise ValueError
        for call, receipt in zip(calls, journal.receipts, strict=True):
            if not isinstance(call, dict):
                raise ValueError
            for name in ("prompt", "completion"):
                if type(call.get(name)) is not int or call[name] != getattr(receipt, name):
                    raise ValueError
            for name in ("provider", "model", "kind"):
                if call.get(name) != getattr(receipt, name):
                    raise ValueError
            estimated = call.get("estimated", False)
            if type(estimated) is not bool or estimated != receipt.estimated:
                raise ValueError
        prompt = sum(item.prompt for item in journal.receipts)
        completion = sum(item.completion for item in journal.receipts)
        for name, expected in (
            ("prompt_tokens", prompt),
            ("completion_tokens", completion),
            ("total_tokens", prompt + completion),
        ):
            if type(result.get(name)) is not int or result[name] != expected:
                raise ValueError
    except (TypeError, ValueError, KeyError):
        raise JobStateUnavailable("Usage checkpoint mismatch") from None
