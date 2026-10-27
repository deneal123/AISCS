"""Read one fenced operation without allocating, dispatching or repeating an effect."""

from service.services.chat.persistence.harness import effects as harness_effects
from service.services.chat.persistence.harness import grants as harness_grants
from service.services.chat.persistence.harness.admission.calls import SERVER_JOB, verified_wire_call
from service.shared.harness_protocol import HarnessFailure, OperationStatus
from service.shared.task_contract import digest_payload


async def inspect_operation(db, row, operation_id: str, kind: str) -> OperationStatus:
    if kind == "paid":
        record = await harness_grants._read(db, row, operation_id)
        status_key, digest_key = "state", "request_digest"
    elif kind == "effect":
        record = await harness_effects.read(db, row, operation_id)
        status_key, digest_key = "status", "intent_digest"
    else:
        raise HarnessFailure("operation_conflict")
    if record is None:
        raise HarnessFailure("operation_conflict")
    digest = record[digest_key]
    if kind == "paid" and SERVER_JOB in record["request"]:
        try:
            # Внутренняя метка окна не меняет digest клиентского intent и ACK.
            digest = digest_payload(verified_wire_call(record["request"], digest))
        except ValueError:
            raise HarnessFailure("operation_conflict") from None
    return OperationStatus(
        operation_id=operation_id,
        operation_kind=kind,
        status=record[status_key],
        request_digest=digest,
        receipt=record["receipt"],
    )
