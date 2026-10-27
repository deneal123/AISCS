"""Closed mutation outcomes; content and private service diagnostics are never public errors."""

EDIT_ERRORS = {
    "ide_command_busy": 423,
    "ide_library_missing": 404,
    "ide_library_unavailable": 503,
    "ide_library_integrity": 409,
    "ide_library_limit": 413,
    "ide_agent_context_invalid": 422,
    "ide_git_url_invalid": 422,
    "ide_git_branch_missing": 422,
    "ide_git_fetch_failed": 502,
    "ide_git_conflict": 409,
    "ide_git_not_empty": 409,
    "ide_git_invalid": 422,
    "ide_git_limit": 413,
    "ide_git_failed": 422,
    "ide_git_unconfirmed": 503,
    "ide_path_forbidden": 403,
    "ide_file_changed": 409,
    "ide_file_missing": 404,
    "ide_file_unsupported": 422,
    "ide_write_limit": 413,
    "ide_runtime_expired": 410,
    "ide_generation_changed": 409,
    "ide_runtime_not_ready": 409,
    "ide_edit_unavailable": 503,
    "ide_edit_session_required": 422,
    "ide_edit_lease_changed": 409,
    "ide_write_unconfirmed": 503,
}


class IdeEditError(Exception):
    def __init__(self, code="ide_edit_unavailable"):
        self.code = code if type(code) is str and code in EDIT_ERRORS else "ide_edit_unavailable"
        super().__init__(self.code)
