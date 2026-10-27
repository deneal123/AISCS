"""Private first-entry identity survives lost replies and ephemeral bindings."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID


class PdfPreparationNotFound(Exception):
    pass


class PdfPreparationUnavailable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PdfPreparationScope:
    thread_id: UUID
    user_id: UUID

    def params(self) -> dict[str, UUID]:
        return {"thread_id": self.thread_id, "user_id": self.user_id}


@dataclass(frozen=True, slots=True)
class PdfPreparation:
    allocation_id: UUID | None
    workspace_id: str | None
    expires_at: int
    scaffold_state: Literal["idle", "dispatching", "rejected", "observed"] = "idle"
