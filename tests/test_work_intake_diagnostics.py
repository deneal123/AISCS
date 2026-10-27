"""Deferred intake diagnostics must not disclose a sidecar payload."""

import logging
from unittest.mock import Mock

import pytest

from service.services.chat.presentation.routers.chat_api import work_intake
from service.services.chat.presentation.routers.chat_api.work_intake import _record_import_deferral


@pytest.fixture
def logger_calls(monkeypatch):
    warning = Mock()
    monkeypatch.setattr(work_intake.logger, "warning", warning)
    return warning


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("source address is not allowed", "source_denied"),
        ("source is temporarily unavailable", "source_transport"),
        ("source rejected the request", "source_rejected"),
        ("stage write failed", "staging_failed"),
        ("publish failed", "publication_failed"),
        ("PRIVATE_EXCEPTION https://private.invalid", "import_incomplete"),
        ({"PRIVATE_EXCEPTION": "secret"}, "import_incomplete"),
    ],
)
def test_import_deferral_projects_only_closed_codes(logger_calls, reason, code):
    _record_import_deferral(
        {"files": [{"name": "PRIVATE_FILE", "reason": reason, "url": "PRIVATE_URL"}]}
    )
    logger_calls.assert_called_once()
    assert logger_calls.call_args.kwargs["extra"] == {
        "failure_code": code,
        "component": "workspace",
    }
    assert "PRIVATE" not in str(logger_calls.call_args)
    assert "private.invalid" not in str(logger_calls.call_args)
    # Deployment's plain text formatter does not render LogRecord.extra.
    # The closed reason must remain observable without changing global logging.
    args = logger_calls.call_args.args
    record = logging.LogRecord("intake", logging.WARNING, "", 0, args[0], args[1:], None)
    rendered = logging.Formatter("%(levelname)s %(message)s").format(record)
    assert code in rendered
    assert "PRIVATE" not in rendered
    assert "private.invalid" not in rendered


def test_deferral_deduplicates_codes_and_ignores_malformed_entries(logger_calls):
    _record_import_deferral(
        {"files": [None, {"reason": "publish failed"}, {"reason": "publish failed"}]}
    )
    assert [call.kwargs["extra"]["failure_code"] for call in logger_calls.call_args_list] == [
        "publication_failed"
    ]


@pytest.mark.parametrize("result", [{}, {"files": None}, {"files": "PRIVATE_PAYLOAD"}])
def test_missing_diagnostics_receive_bounded_fallback(logger_calls, result):
    _record_import_deferral(result)
    assert [call.kwargs["extra"]["failure_code"] for call in logger_calls.call_args_list] == [
        "import_incomplete"
    ]
    assert "PRIVATE" not in str(logger_calls.call_args_list)
