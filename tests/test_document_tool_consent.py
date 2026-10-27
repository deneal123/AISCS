from types import SimpleNamespace

import pytest

from service.application.admission.document_tools import apply_document_tool_consent
from service.domain.execution.context import PrivateRunResources, RunExecutionContext


@pytest.mark.parametrize("approved", [True, False, None, "true"])
@pytest.mark.parametrize("declined", [True, False])
def test_only_backend_approved_owned_pdf_grants_tool_consent(approved, declined):
    execution = RunExecutionContext(
        resources=PrivateRunResources(
            workspace_ref={
                "document_context": {
                    "path": "documents/paper",
                    "project_id": "owned-project",
                    "tools_auto_approved": approved,
                },
            }
        )
    )
    execution.capabilities = SimpleNamespace(
        tools={
            "video": SimpleNamespace(
                confirm_by_default=True, requires_context_attr="video_tool_enabled"
            ),
            "table": SimpleNamespace(
                confirm_by_default=False, requires_context_attr="tabular_files"
            ),
        }
    )
    execution.policy.set_flag("confirmation_declined", declined)
    expected = approved is True and not declined
    assert apply_document_tool_consent(execution) is expected
    assert execution.policy.flag("document_tools_auto_approved") is expected
    assert execution.policy.flag("document_patch_enabled") is expected
    assert execution.policy.flag("video_tool_enabled") is expected
    assert not execution.policy.flag("tabular_files")


def test_normal_chat_and_incomplete_document_context_do_not_auto_approve():
    for ref in (None, {}, {"document_context": {"tools_auto_approved": True}}):
        execution = RunExecutionContext(resources=PrivateRunResources(workspace_ref=ref))
        assert not apply_document_tool_consent(execution)
        assert not execution.policy.flag("document_patch_enabled")


def test_pdf_patch_is_available_without_the_auto_planners_file_flag():
    from service.domain.execution.context import use_run_execution
    from service.domain.subagents.general import GeneralAgent

    resources = PrivateRunResources(
        workspace_ref={
            "document_context": {
                "path": "documents/slides",
                "project_id": "owned-project",
                "tools_auto_approved": True,
            },
        }
    )
    with use_run_execution(resources) as execution:
        assert apply_document_tool_consent(execution)
        assert not execution.policy.flag("workspace_tools_enabled")
        tools = GeneralAgent({"model": "test-model"})._applicable_tools(None)
        assert "tex_propose_patch" in {tool.name for tool in tools}
        assert not execution.policy.flag("workspace_tools_enabled")
