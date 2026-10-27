"""Metadata projection does not stringify or retain integration diagnostics."""

import pytest

from service.services.files.domain.file_scan_result import safe_scan_result


@pytest.mark.parametrize("value", [None, [], "PRIVATE_SCAN_BODY", 1])
def test_non_mapping_result_is_not_accepted(value):
    assert safe_scan_result(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            {"status": "error", "reason": "PRIVATE_SCAN_BODY", "exception": object()},
            {"status": "error", "reason": "unavailable"},
        ),
        (
            {"status": "skipped", "reason": "no_download", "url": "PRIVATE_SCAN_URL"},
            {"status": "skipped", "reason": "no_download"},
        ),
        (
            {"status": "ok", "size": 2**53 - 1, "sha256": "f" * 64, "body": object()},
            {"status": "ok", "size": 2**53 - 1, "sha256": "f" * 64},
        ),
    ],
)
def test_only_existing_closed_metadata_fields_survive(value, expected):
    original = dict(value)
    assert safe_scan_result(value) == expected
    assert value == original
