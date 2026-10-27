"""Подтверждённое чтение сохраняется вместе с receipt, не меняя версию исходников."""

from service.services.chat.persistence.harness.commands.evidence import latest_evidence
from service.services.chat.persistence.harness.state import save_checkpoint


async def record_read_evidence(db, row, receipt, current):
    # Вызывается только после полной проверки effects.record в той же транзакции.
    # Повтор старого receipt не переименовывает его версию в текущую.
    if current.admission.surface != "ide" or receipt.status != "succeeded" or current.state is None:
        return
    state = current.state
    proofs = [
        proof
        for proof in receipt.evidence
        if proof.kind == "read" and proof.source_revision == state.source_revision
    ]
    if not proofs:
        return
    combined = latest_evidence(state.evidence, proofs)
    if tuple(combined) == state.evidence:
        return
    await save_checkpoint(
        db, row, state=state.advance(evidence=combined), continuation=current.continuation
    )
