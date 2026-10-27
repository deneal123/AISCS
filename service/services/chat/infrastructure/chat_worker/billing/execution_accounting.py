"""Durable private reservation facts, not permission to replay or charge a model."""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerRunRequest,
)
from service.services.jobs.persistence.transitions import ACCOUNTING_KEY, EXECUTION_KEY


@dataclass(frozen=True, slots=True)
class ExecutionAccounting:
    attempt_id: str
    reservation_id: str | None
    reserved_estimate: int

    @classmethod
    def decode(cls, value: Any) -> "ExecutionAccounting":
        try:
            if not isinstance(value, dict) or set(value) != {
                "schema_version",
                "attempt_id",
                "reservation_id",
                "reserved_estimate",
            }:
                raise ValueError
            if type(value["schema_version"]) is not int or value["schema_version"] != 1:
                raise ValueError
            attempt = value["attempt_id"]
            reservation = value["reservation_id"]
            if not isinstance(attempt, str) or str(UUID(attempt)) != attempt:
                raise ValueError
            if reservation is not None and (
                not isinstance(reservation, str) or str(UUID(reservation)) != reservation
            ):
                raise ValueError
            estimate = value["reserved_estimate"]
            if type(estimate) is not int or not 0 <= estimate <= 1_000_000_000:
                raise ValueError
            if reservation is None and estimate != 0:
                raise ValueError
            return cls(attempt, reservation, estimate)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise JobStateUnavailable("Execution accounting unavailable") from None

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "attempt_id": self.attempt_id,
            "reservation_id": self.reservation_id,
            "reserved_estimate": self.reserved_estimate,
        }


async def stage_execution_accounting(
    repository: Any, session: Any, request: WorkerRunRequest, state: MutableRunState
) -> None:
    """Stage under the owned row lock; preflight commit remains the only ACK.

    No capability, request, URL or settings snapshot is stored. A reservation
    created before an interrupted checkpoint still requires reconciliation.
    """
    try:
        facts = ExecutionAccounting.decode(
            {
                "schema_version": 1,
                "attempt_id": state.execution_attempt_id,
                "reservation_id": state.reservation_id,
                "reserved_estimate": state.reserved_estimate,
            }
        )
        job = UUID(request.job_id)
        owner = UUID(str(request.user_id))
        row = await repository.lock_prepared_turn(job, owner, session=session)
        if row is None or row["status"] != ProcessingStatus.PROCESSING:
            raise ValueError
        payload = row.get("payload") or {}
        if payload.get("thread_id") != request.thread_id:
            raise ValueError
        if payload.get(EXECUTION_KEY) != facts.attempt_id:
            raise ValueError
        if ACCOUNTING_KEY in payload:
            if ExecutionAccounting.decode(payload[ACCOUNTING_KEY]) != facts:
                raise ValueError
            return
        saved = await repository.stage_execution_accounting(
            job,
            owner,
            request.thread_id,
            facts.attempt_id,
            json.dumps(facts.payload(), separators=(",", ":")),
            session=session,
        )
        if saved is not True:
            raise ValueError
    except Exception:
        raise JobStateUnavailable("Execution accounting unavailable") from None
