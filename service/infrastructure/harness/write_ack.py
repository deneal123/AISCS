"""Recover only the backend's typed IDE write-version normalization after lost ACK."""

from service.shared.harness_protocol import EffectResult, Snapshot


async def reconciled_write_snapshot(submitted, recorded, prior, query):
    if (
        prior is None
        or prior.state is None
        or prior.admission.surface != "ide"
        or not isinstance(recorded, EffectResult)
        or submitted.status != "succeeded"
        or any(item.kind != "file" for item in submitted.evidence)
    ):
        return None
    revision = "write:" + submitted.operation_id
    normalized = submitted.model_copy(
        update={
            "evidence": tuple(
                item.model_copy(update={"source_revision": revision}) for item in submitted.evidence
            )
        }
    )
    # No field other than the executor-owned version is allowed to differ.
    if recorded != normalized:
        return None
    raw = await query(opcode="state")
    current = Snapshot.model_validate(raw["snapshot"])
    state = current.state
    if (
        current.admission != prior.admission
        or current.stopped
        or current.revision < prior.revision
        or current.continuation != prior.continuation
        or state is None
        or state.contract != prior.state.contract
        or state.rounds != prior.state.rounds
        or state.repairs != prior.state.repairs
        or state.protocol_repairs != prior.state.protocol_repairs
        or state.source_revision != revision
        or not all(item in state.evidence for item in normalized.evidence)
    ):
        return None
    return current.model_dump(mode="json")
