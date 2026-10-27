"""Реальная локальная CPU-модель и сервисы, без внешних платных провайдеров."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(os.getenv("HARNESS_LOCAL_MODEL_LIVE") != "1", reason="real CPU model opt-in")
def test_local_model_creates_and_verifies_current_project():
    result = run_command_probe(agents=True, provider="local", local_model=True)
    assert result["local_model_ide_verified"] and result["commands"] >= 1
