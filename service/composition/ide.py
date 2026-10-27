"""One runtime composition owner for repository UI and agent context resolution."""

from functools import partial
from typing import Any

from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.persistence.harness.commands.gate import require_mutation_available
from service.services.chat.persistence.ide.repositories import IdeRepositoryRepository
from service.services.chat.persistence.ide.runtime import IdeRuntimeRepository
from service.settings import config


def build_ide_runtime(connector: Any) -> IdeRuntimeService:
    return IdeRuntimeService(
        IdeRepositoryRepository(connector),
        IdeRuntimeRepository(connector),
        IdeWorkspaceClient(config.agents),
        mutation_guard=partial(require_mutation_available, connector),
    )
