"""Copy an owned Library object to one explicitly selected repository path."""

from uuid import UUID

from service.services.chat.application.ide.edits import IdeEditService
from service.services.chat.application.workspace_collaboration import (
    CollaborationConflict,
    CollaborationError,
    verify_capability,
)
from service.services.chat.domain.ide.edits import IdeEditError
from service.services.chat.domain.ide.files import validate_path
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.files.application.file_saver_service import FileSaverService
from service.services.files.application.library_read import LibraryReadFailure


async def copy_library_file(
    edits: IdeEditService,
    files: FileSaverService,
    scope: RepositoryScope,
    *,
    file_id: UUID,
    path: str,
    generation: str,
    session: str | None,
    fence: int,
) -> dict:
    path = validate_path(path)
    try:
        resolved, capability, store = await edits._context(scope, generation, session)
        checked = await store.preflight(
            verify_capability(capability),
            mutation="write",
            path=path,
            fence=fence,
        )
        data = await files.read_chat_library_bytes(scope.user_id, file_id)
        await edits._current(scope, resolved)
        result = await edits.runtime.client.write(
            scope.user_id,
            resolved.binding,
            path=path,
            operation="import",
            content=data,
            expected_digest=None,
            capability=capability,
            fence=checked["fence"],
        )
        await edits._current(scope, resolved)
        return {"repository_id": str(scope.repository_id), "generation": generation, **result}
    except LibraryReadFailure as error:
        raise IdeEditError(error.code) from None
    except CollaborationConflict:
        raise IdeEditError("ide_edit_lease_changed") from None
    except CollaborationError:
        raise IdeEditError() from None
