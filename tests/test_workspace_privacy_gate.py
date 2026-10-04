"""Root privacy gate covers multiline workspace diagnostic regressions."""

import importlib.util
from pathlib import Path

import pytest


def gate():
    path = Path(__file__).resolve().parents[2] / "scripts" / "check_privacy_boundaries.py"
    if not path.is_file():
        pytest.skip("root-only privacy gate is not shipped in the standalone sidecar")
    spec = importlib.util.spec_from_file_location("workspace_privacy_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "source",
    [
        'logger.exception("static")',
        'logger.error("static",\n exc_info=True)',
        'logger.error("static",\n exc_info=error)',
        'logger.error("static",\n extra={"private": ref.container_id})',
    ],
)
def test_gate_rejects_multiline_traceback_and_identity_diagnostics(source):
    assert gate().has_unsafe_workspace_log(source)


def test_gate_accepts_closed_codes_without_traceback():
    assert not gate().has_unsafe_workspace_log(
        'logger.error("static", exc_info=False,\n'
        'extra={"component": "workspace_driver", "failure_code": "cleanup_failed"})'
    )
