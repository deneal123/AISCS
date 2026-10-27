"""Backend authority is an explicit runtime flag plus exactly one owned project."""

import pytest

from service.services.chat.infrastructure.chat_worker.engine_env import _question_capability
from service.settings import config


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    "targets",
    [
        {},
        {"ide_context": {}},
        {"document_context": {}},
        {"ide_context": {}, "document_context": {}},
    ],
)
def test_only_feature_enabled_project_runs_receive_server_question_capability(
    monkeypatch, enabled, targets
):
    monkeypatch.setattr(config.human_questions, "enabled", enabled)
    env = {"workspace_ref": {"token": "PRIVATE", **targets}}
    assert _question_capability(env) is env
    assert (env["workspace_ref"].get("human_questions_enabled") is True) == (
        enabled and len(targets) == 1
    )
    assert "human_questions_enabled" not in _question_capability({})
