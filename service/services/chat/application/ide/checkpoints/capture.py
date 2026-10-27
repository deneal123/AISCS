"""Explicit generation-fenced capture -> existing immutable checkpoint publication.

Public composition supplies explicit retention/quota/deletion policy. Replay
reconciles the original intent, never recaptures or substitutes a live generation.
"""

from uuid import UUID

from service.infrastructure.ide.transports.capture import CapturePolicy
from service.services.chat.application.ide.checkpoints.service import IdeCheckpointService
from service.services.chat.application.ide.edits import IdeEditService, validate_ide_session
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.application.workspace_collaboration import (
    CollaborationError,
    verify_capability,
)
from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.checkpoints.revision import CheckpointIntent, CheckpointRecord
from service.services.chat.domain.ide.runtime import RepositoryScope, allocation_generation_tag


async def capture_checkpoint(
    edits: IdeEditService,
    checkpoints: IdeCheckpointService,
    scope: RepositoryScope,
    *,
    checkpoint_id: UUID,
    base_checkpoint_id: UUID | None,
    generation: str,
    session: str | None,
    limits: CapturePolicy,
) -> CheckpointRecord:
    validate_ide_session(session)
    if not isinstance(checkpoint_id, UUID) or (
        base_checkpoint_id is not None
        and (not isinstance(base_checkpoint_id, UUID) or base_checkpoint_id == checkpoint_id)
    ):
        raise IdeCheckpointError()
    try:
        previous = await checkpoints.status(scope, checkpoint_id)
    except IdeRepositoryNotFound:
        previous = None
    if previous is not None:
        if (
            previous.intent.base_checkpoint_id != base_checkpoint_id
            or allocation_generation_tag(previous.intent.allocation_id) != generation
        ):
            raise IdeCheckpointError("ide_checkpoint_intent_mismatch")
        return await checkpoints.reconcile(scope, checkpoint_id)
    if (
        not isinstance(limits, CapturePolicy)
        or limits.archive_bytes > checkpoints.storage.max_bytes
    ):
        raise IdeCheckpointError()
    namespace = checkpoints.storage.namespace
    try:
        resolved, capability, store = await edits._context(scope, generation, session)
        checked = verify_capability(capability)
        await store.preflight(checked, mutation="capture")
        await edits._current(scope, resolved)
        async with edits.runtime.client.capture(
            scope.user_id,
            resolved.binding,
            capability=capability,
            limits=limits,
        ) as capsule:
            await edits._current(scope, resolved)
            await store.preflight(checked, mutation="capture")
            intent = CheckpointIntent(
                CheckpointBlob(scope, checkpoint_id, capsule.sha256, capsule.size),
                resolved.attempt.allocation_id,
                base_checkpoint_id,
                namespace,
            )
            # reserve/publish recheck owned allocation/expiry and CAS HEAD in
            # short DB transactions. No runtime operation lock spans upload.
            return await checkpoints.save(scope, intent, capsule.source)
    except CollaborationError:
        raise IdeCheckpointError("ide_checkpoint_capture_unavailable") from None
