"""Private row-locked transition policy; no payload enters diagnostics."""

from typing import Any

from service.models.key_value import ProcessingStatus
from service.shared.repositories.exceptions import RepositoryError

RECOVERY_KEYS = ("_accepted_turn_v1", "_prepared_turn_v1", "_materialization_plan_v1")
TERMINAL = (ProcessingStatus.SUCCESS, ProcessingStatus.FAILURE)
# Private JSON field identifier, not a credential.
EXECUTION_KEY = "_execution_attempt_v1"  # gitleaks:allow
USAGE_JOURNAL_KEY = "_usage_journal_v1"
ACCOUNTING_KEY = "_execution_accounting_v1"
HARNESS_KEY = "_harness_task_v1"
HARNESS_RETRY_KEY = "_harness_transport_retry_v1"
DOCUMENT_SCOPE_KEY = "_harness_document_scope_v1"


def recovery_facts(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload[key] for key in RECOVERY_KEYS if key in payload}


def guarded_payload(
    stored_status: ProcessingStatus,
    stored_payload: dict[str, Any] | None,
    incoming_status: ProcessingStatus,
    incoming_payload: dict[str, Any] | None,
    expected_recovery: dict[str, Any] | None,
) -> dict[str, Any] | None:
    stored = stored_payload or {}
    incoming = incoming_payload or {}
    if stored_status in TERMINAL and (incoming_status != stored_status or incoming != stored):
        raise RepositoryError("Job transition unavailable")
    facts = recovery_facts(stored)
    if expected_recovery is not None and expected_recovery != facts:
        raise RepositoryError("Job transition unavailable")
    if incoming_status in TERMINAL and facts:
        if incoming_status == ProcessingStatus.FAILURE or expected_recovery is None:
            raise RepositoryError("Job transition unavailable")
        incoming = {key: value for key, value in incoming.items() if key not in RECOVERY_KEYS}
    else:
        for key in RECOVERY_KEYS:
            if key in incoming and (key not in facts or incoming[key] != facts[key]):
                raise RepositoryError("Job transition unavailable")
        incoming = {**incoming, **facts}
    if stored.get("_cancel_requested_v1") is True:
        incoming = {**incoming, "_cancel_requested_v1": True}
    for key in (
        EXECUTION_KEY,
        USAGE_JOURNAL_KEY,
        ACCOUNTING_KEY,
        HARNESS_KEY,
        HARNESS_RETRY_KEY,
        DOCUMENT_SCOPE_KEY,
    ):
        if key in incoming and incoming[key] != stored.get(key):
            raise RepositoryError("Job transition unavailable")
        if key in stored:
            incoming = {**incoming, key: stored[key]}
    return incoming if incoming or incoming_payload is not None else None
