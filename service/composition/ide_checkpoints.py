"""One explicit-budget composition for public Save/history/restore."""

from typing import Any

from service.composition.models import InfraContainer
from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
from service.infrastructure.ide.transports.capture import CapturePolicy
from service.services.chat.application.ide.checkpoints.restore import IdeRestoreService
from service.services.chat.application.ide.checkpoints.retention import (
    IdeCheckpointRetentionService,
)
from service.services.chat.application.ide.checkpoints.saved_projects import IdeSavedProjects
from service.services.chat.application.ide.checkpoints.service import IdeCheckpointService
from service.services.chat.application.ide.edits import IdeEditService
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.ide.checkpoints.blob import IdeCheckpointError
from service.services.chat.domain.ide.checkpoints.budget import CheckpointStorageBudget
from service.services.chat.persistence.ide.checkpoints.repository import IdeCheckpointRepository
from service.services.chat.persistence.ide.checkpoints.restore import IdeRestoreRepository
from service.services.chat.persistence.ide.checkpoints.retention import (
    IdeCheckpointRetentionRepository,
)
from service.shared.ide_checkpoint_settings import IdeCheckpointConfig


def build_saved_projects(
    infra: InfraContainer, runtime: IdeRuntimeService, redis: Any, options: IdeCheckpointConfig
) -> IdeSavedProjects:
    if not options.enabled or infra.storage is None:
        raise IdeCheckpointError("ide_checkpoint_storage_unavailable")
    storage = IdeCheckpointStorage(infra.storage, max_bytes=options.max_snapshot_bytes)
    limits = CapturePolicy(
        options.entries,
        options.max_file_bytes,
        options.max_total_bytes,
        options.max_snapshot_bytes,
        options.manifest_bytes,
        options.depth,
    )
    budget = CheckpointStorageBudget(
        options.max_user_bytes, options.max_snapshot_bytes, options.max_pending_per_repository
    )
    checkpoints = IdeCheckpointService(
        IdeCheckpointRepository(infra.pg_connector),
        storage,
        budget=budget,
        historical=True,
        retention=IdeCheckpointRetentionService(
            IdeCheckpointRetentionRepository(infra.pg_connector), storage
        ),
    )
    return IdeSavedProjects(
        IdeEditService(runtime, redis),
        checkpoints,
        IdeRestoreService(
            IdeRestoreRepository(infra.pg_connector), checkpoints, runtime.client, limits=limits
        ),
        limits=limits,
    )
