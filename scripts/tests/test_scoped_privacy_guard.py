import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "check_privacy_boundaries.py"
spec = importlib.util.spec_from_file_location("scoped_privacy_gate", PATH)
assert spec is not None and spec.loader is not None
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


@pytest.mark.parametrize(
    "source",
    ['logger.exception("failed")', 'logger.debug("failed", exc_info=True)', "str(exc)"],
)
def test_billing_metrics_rule_rejects_raw_failure(source):
    pattern = next(
        pattern
        for name, _, pattern in gate.RULES
        if name == "billing_metrics_raw_failure"
    )
    assert pattern.search(source)


def test_billing_metrics_rule_allows_static_bounded_diagnostics():
    pattern = next(
        pattern
        for name, _, pattern in gate.RULES
        if name == "billing_metrics_raw_failure"
    )
    assert not pattern.search(
        'logger.debug("unavailable", extra={"component":"billing_metrics",'
        '"failure_code":"unavailable"})'
    )


@pytest.mark.parametrize(
    "source",
    [
        'logger.exception("failed")',
        'logger.warning("failed", exc_info=True)',
        'logger.info("task %s",\n task_name)',
    ],
)
def test_background_manager_rule_rejects_raw_failure_or_dynamic_identity(source):
    pattern = next(
        pattern
        for name, _, pattern in gate.RULES
        if name == "background_manager_raw_failure"
    )
    assert pattern.search(source)


@pytest.mark.parametrize(
    "body",
    [
        'logger.debug("failed", exc_info=True)',
        'logger.exception("failed")',
        'logger.warning("failed %s", response.text)',
    ],
)
def test_guard_rejects_raw_target_diagnostics(body):
    source = f"async def target():\n    {body}\n"
    assert gate.has_unsafe_scoped_log(source, "target")


def test_guard_is_exact_and_does_not_hide_unmigrated_siblings():
    source = (
        'async def target():\n    logger.debug("failed", extra={"failure_code": "unavailable"})\n'
        'async def sibling():\n    logger.exception("debt")\n'
    )
    assert not gate.has_unsafe_scoped_log(source, "target")
    assert gate.has_unsafe_scoped_log(source, "sibling")


@pytest.mark.parametrize(
    "source", ["", "invalid source!", "def target(): pass\ndef target(): pass"]
)
def test_missing_invalid_or_ambiguous_target_fails_closed(source):
    assert gate.has_unsafe_scoped_log(source, "target")


@pytest.mark.parametrize(
    "function", [
        "_presign", "_dialog_file_rows", "_report_missing_rows", "_file_is_tabular",
        "_recall_or_persist_thread_tabular", "_forget_thread_files",
        "read_thread_repo_graphs", "collect_message_extras", "recall_last_thread_image_url",
    ]
)
def test_attachment_context_failure_seams_are_mandatory_scoped_targets(function):
    targets = {(path.relative_to(gate.ROOT).as_posix(), name) for path, name in gate.SCOPED_LOG_FUNCTIONS}
    module = "repository_references" if function == "read_thread_repo_graphs" else "agent_context"
    assert (f"backend/service/services/chat/infrastructure/{module}.py", function) in targets


@pytest.mark.parametrize(
    "relative_path",
    [
        "backend/service/services/chat/infrastructure/chat_worker/billing/usage/journal.py",
        "backend/service/infrastructure/ide/transports/console.py",
        "backend/service/services/analytics/application/memory/service.py",
        "backend/service/services/analytics/application/memory/usage.py",
    ],
)
def test_private_worker_and_ide_boundaries_remain_scanned_after_nested_package_moves(relative_path):
    assert gate.ROOT / relative_path in gate.BOUNDARY_LOG_FILES
