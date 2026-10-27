"""Диагностика приёмки не раскрывает тексты и не меняет финансовые решения."""

import json

import pytest

from scripts.harness.live.delivery_diagnostics import delivery_diagnostic


@pytest.mark.parametrize("result", [None, "PRIVATE_SECRET", [], Exception("PRIVATE_SECRET")])
def test_non_object_result_never_stringifies_content(result):
    assert delivery_diagnostic(result) == {
        "stage": "worker_delivery",
        "delivery_status": "invalid_result",
    }


def test_success_remains_unchanged_and_has_no_diagnostic_payload():
    result = {"status": "success", "text": "PRIVATE_TRANSCRIPT"}
    before = dict(result)
    assert delivery_diagnostic(result) is None
    assert result == before


@pytest.mark.parametrize("value", ["PRIVATE_CAPABILITY", [], {}, True, 10000])
def test_untrusted_status_code_or_error_text_is_not_exposed(value):
    actual = delivery_diagnostic(
        {
            "status": value,
            "error_code": value,
            "status_code": value,
            "error": "PRIVATE_REQUEST",
            "metadata": {"token": "PRIVATE_TOKEN"},
        }
    )
    assert actual == {
        "stage": "worker_delivery",
        "delivery_status": "other",
        "error_code": "other",
        "http_status": None,
    }
    assert "PRIVATE" not in json.dumps(actual)


def test_closed_failure_projection_preserves_only_known_categories():
    assert delivery_diagnostic(
        {
            "status": "error",
            "error_code": "chat_service_error",
            "status_code": 503,
            "error": "PRIVATE_INTERNAL_ADDRESS",
        }
    ) == {
        "stage": "worker_delivery",
        "delivery_status": "error",
        "error_code": "chat_service_error",
        "http_status": 503,
    }
